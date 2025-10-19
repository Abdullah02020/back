# products/views.py
# ============================================================
# Imports
# ============================================================
import time
import uuid
from decimal import Decimal, ROUND_HALF_UP
from collections import defaultdict
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q, F, Sum, Func
from django.db.models.functions import Coalesce
from django.views.decorators.cache import cache_page
from django.contrib.contenttypes.models import ContentType
from django.template.loader import render_to_string
from django.http import HttpResponse

from rest_framework import viewsets, filters, permissions, status
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    Product,
    Sales,
    Tenant,
    Branch,
    Agent,
    Invoice,
    Inventory,
)
from .serializers import (
    ProductSerializer,
    CreateOrderSerializer,
    OrderCreatedSerializer,
)
from .services import create_invoice_for_order

from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.conf import settings

from .models import Tenant, Warehouse, Product, Agent
from .services import receive_to_warehouse, StockError

# ============================================================
# ProductViewSet
# ============================================================
class ProductViewSet(viewsets.ModelViewSet):
    """
    /api/products/
      - q=beef
      - category=breads
      - active=true|false      # يُطبق على status
      - ordering=price|-price|name|updated_at
      - page=1
    """
    permission_classes = [permissions.AllowAny]  # لاحقًا غيّرها إلى IsAuthenticated

    # alias حتى نقدر نرتّب بـ updated_at ونستعلم عن active
    queryset = (
        Product.objects
        .alias(updated_at=F("last_modified"), active=F("status"))
        .order_by("-updated_at")
    )
    serializer_class = ProductSerializer

    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["name", "sku", "category"]
    ordering_fields = ["price", "updated_at", "name"]     # نسمح بالـ alias
    ordering = ["-updated_at"]

    # -------- helpers --------
    def _agent_id(self) -> int | None:
        """
        يحاول يجلب Agent ID من المستخدم المصادَق.
        لو ما في مستخدم/ربط Agent، يستخدم DEFAULT_AGENT_ID من settings للتجارب.
        تأكد أن DEFAULT_AGENT_ID يشير إلى Agent موجود فعلًا.
        """
        agent = getattr(getattr(self.request.user, "agent", None), "pk", None)
        if agent:
            return agent
        return getattr(settings, "DEFAULT_AGENT_ID", None)

    # -------- list/query --------
    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params

        # فلترة category
        cat = params.get("category")
        if cat:
            qs = qs.filter(category__iexact=cat)

        # فلترة active -> status
        active = params.get("active")
        if active in ("true", "false"):
            qs = qs.filter(status=(active == "true"))

        # q (بالإضافة لـ SearchFilter)
        q = params.get("q")
        if q:
            qs = qs.filter(
                Q(name__icontains=q) |
                Q(sku__icontains=q) |
                Q(category__icontains=q)
            )
        return qs

    # -------- create/update --------
    def perform_create(self, serializer):
        now = int(time.time())
        agent_id = self._agent_id()
        serializer.save(
            created_by_id=agent_id,
            modified_by_id=agent_id,
            date_created=now,
            last_modified=now,
        )

    def perform_update(self, serializer):
        agent_id = self._agent_id()
        serializer.save(
            modified_by_id=agent_id,
            last_modified=int(time.time()),
        )

    # -------- extra endpoints --------
    @action(detail=False, methods=["GET"], url_path="stats")
    def stats(self, request):
        base = self.get_queryset()
        return Response({
            "total": base.count(),
            "active": base.filter(status=True).count(),
        })


# ============================================================
# OrdersView (Class-based)
# ============================================================
class OrdersView(APIView):
    permission_classes = [permissions.AllowAny]

    def _get_defaults(self, request):
        tenant_id = getattr(settings, "DEFAULT_TENANT_ID", "Z0")
        branch_id = getattr(settings, "DEFAULT_BRANCH_ID", 1)
        agent_id  = getattr(settings, "DEFAULT_AGENT_ID", None)
        req_agent = getattr(getattr(request.user, "agent", None), "pk", None)
        if req_agent is not None:
            agent_id = req_agent
        return tenant_id, branch_id, agent_id

    @transaction.atomic
    def post(self, request):
        data = request.data or {}
        want_debug = bool(data.get("debug"))
        lines = data.get("lines") or []
        if not isinstance(lines, list) or not lines:
            return Response({"detail": "lines is required"}, status=400)

        try:
            tax_rate = Decimal(str(data.get("tax_rate", "0")))
        except Exception:
            tax_rate = Decimal("0")
        if tax_rate > 1:
            tax_rate = (tax_rate / Decimal("100"))

        payment_method = (data.get("payment_method") or "cash").lower()
        currency = getattr(settings, "DEFAULT_CURRENCY", "USD")

        tenant_id, branch_id, agent_id = self._get_defaults(request)
        try:
            tenant = Tenant.objects.get(pk=tenant_id)
        except Tenant.DoesNotExist:
            return Response({"detail": f"Tenant {tenant_id} not found"}, status=400)
        branch = Branch.objects.filter(pk=branch_id).first()
        if branch is None:
            return Response({"detail": f"Branch {branch_id} not found"}, status=400)
        agent = Agent.objects.filter(pk=agent_id).first() if agent_id is not None else None

        now_unix = int(time.time())
        order_id = f"POS-{now_unix}-{uuid.uuid4().hex[:6].upper()}"
        ct_branch = ContentType.objects.get(app_label="products", model="branch")

        wanted = []
        for ln in lines:
            pid = ln.get("product_id")
            qty = int(ln.get("qty", 0))
            if not pid or qty <= 0:
                return Response({"detail": "invalid line"}, status=400)
            wanted.append((int(pid), qty))

        product_ids = [pid for pid, _ in wanted]
        products = (
            Product.objects
            .select_for_update()
            .filter(id__in=product_ids, tenant=tenant, status=True)
        )
        pmap = {p.id: p for p in products}
        missing = [pid for pid in product_ids if pid not in pmap]
        if missing:
            return Response({"detail": f"Products not found or inactive: {missing}"}, status=400)

        # تشخيص إجمالي المخزون مسبقًا
        agg = (
            Inventory.objects
            .filter(
                tenant=tenant,
                product_id__in=product_ids,
                content_type_id=ct_branch.id,
                object_id=branch.id
            )
            .values("product_id")
            .annotate(total_qty=Sum("qty"))
        )
        total_map = {row["product_id"]: int(row["total_qty"] or 0) for row in agg}

        for pid, qty in wanted:
            total_available = total_map.get(pid, 0)
            if total_available < qty:
                product = pmap[pid]
                debug_rows = []
                if want_debug:
                    debug_rows = list(
                        Inventory.objects.filter(
                            tenant=tenant, product_id=pid,
                            content_type_id=ct_branch.id, object_id=branch.id
                        ).values("id","qty","tenant_id","product_id","content_type_id","object_id")
                    )
                return Response(
                    {
                        "detail": "insufficient_stock",
                        "product_id": product.id,
                        "product_name": product.name,
                        "available": int(total_available),
                        "wanted": int(qty),
                        "branch_id": branch.id,
                        "ct_branch_id": ct_branch.id if want_debug else None,
                        "inv_rows": debug_rows if want_debug else None,
                    },
                    status=status.HTTP_409_CONFLICT
                )

        subtotal = Decimal("0")
        out_lines = []

        # استهلاك FIFO + إنشاء سطور البيع
        for pid, qty in wanted:
            product = pmap[pid]
            invs = (
                Inventory.objects
                .select_for_update()
                .only("id", "qty")
                .filter(
                    tenant=tenant,
                    product=product,
                    content_type_id=ct_branch.id,
                    object_id=branch.id
                )
                .order_by("id")
            )

            remaining = int(qty)
            for rec in invs:
                if remaining <= 0:
                    break
                take = min(int(rec.qty), remaining)
                if take > 0:
                    rec.qty = F("qty") - take
                    rec.save(update_fields=["qty"])
                    remaining -= take

            new_total = (
                Inventory.objects
                .filter(
                    tenant=tenant,
                    product=product,
                    content_type_id=ct_branch.id,
                    object_id=branch.id
                )
                .aggregate(s=Sum("qty"))["s"] or 0
            )

            unit_price = Decimal(product.price)
            line_subtotal = unit_price * qty
            line_tax = (line_subtotal * tax_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            line_total = (line_subtotal + line_tax).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            sale = Sales.objects.create(
                tenant=tenant, branch=branch, warehouse=None, product=product,
                promotion_campaign=None, loyalty_benefits=None,
                unit_sold=qty, unit_price_snapshot=unit_price,
                discount_value_applied=Decimal("0"),
                tax_value_applied=line_tax, line_total=line_total,
                currency=currency, order_id=order_id, receipt_no=None,
                product_sku_snapshot=product.sku, product_name_snapshot=product.name,
                branch_name_snapshot=branch.name, created_by=agent, modified_by=agent,
            )

            out_lines.append({
                "product_id": product.id,
                "name": product.name,
                "qty": int(qty),
                "unit_price": f"{unit_price:.2f}",
                "tax": f"{line_tax:.2f}",
                "line_total": f"{line_total:.2f}",
                "new_stock": int(new_total),
                "sale_id": sale.id,
                "order_id": order_id,
            })
            subtotal += line_subtotal

        tax_total = (subtotal * tax_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total = (subtotal + tax_total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        resp = {
            "order_id": order_id,
            "receipt_no": None,
            "payment_method": payment_method,
            "currency": currency,
            "subtotal": f"{subtotal:.2f}",
            "tax": f"{tax_total:.2f}",
            "total": f"{total:.2f}",
            "created_at": now_unix,
            "lines": out_lines,
        }
        if want_debug:
            resp["debug"] = {"branch_id": branch.id, "ct_branch_id": ct_branch.id}
        return Response(resp, status=status.HTTP_201_CREATED)


# ============================================================
# create_order (Function-based)
# ============================================================
@api_view(["POST"])
@transaction.atomic
def create_order(request):
    s = CreateOrderSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    data = s.validated_data
    want_debug = bool(data.get("debug"))

    tenant_id = getattr(settings, "DEFAULT_TENANT_ID", "Z0")
    currency  = getattr(settings, "DEFAULT_CURRENCY", "USD")
    payment_method = (data.get("payment_method") or "cash").lower()

    try:
        tenant = Tenant.objects.get(pk=tenant_id)
    except Tenant.DoesNotExist:
        return Response({"detail": f"Tenant '{tenant_id}' not found."}, status=400)

    branch = None
    branch_id = getattr(settings, "DEFAULT_BRANCH_ID", None)
    if branch_id:
        branch = Branch.objects.filter(pk=branch_id).first()
    if branch is None:
        branch = Branch.objects.first()
    if branch is None:
        return Response({"detail": "No branch found (create at least one Branch)."}, status=400)

    agent_pk = getattr(getattr(request.user, "agent", None), "pk", None)
    agent_obj = None
    if agent_pk:
        agent_obj = Agent.objects.filter(pk=agent_pk).first()
    if agent_obj is None:
        default_agent = getattr(settings, "DEFAULT_AGENT_ID", None)
        if default_agent:
            agent_obj = Agent.objects.filter(pk=default_agent).first()
    if agent_obj is None:
        agent_obj = Agent.objects.first()
    if agent_obj is None:
        return Response({"detail": "No agent available to attribute the order."}, status=400)

    try:
        tax_rate = Decimal(str(data.get("tax_rate", "0.0")))
    except Exception:
        tax_rate = Decimal("0.0")
    if tax_rate > 1:
        tax_rate = (tax_rate / Decimal("100"))

    wanted = defaultdict(int)
    for line in data["lines"]:
        wanted[int(line["product_id"])] += int(line["qty"])

    product_ids = list(wanted.keys())
    order_id = f"POS-{int(time.time())}-{uuid.uuid4().hex[:6].upper()}"
    now_unix = int(time.time())

    ct_branch = ContentType.objects.get(app_label="products", model="branch")

    products = (
        Product.objects.select_for_update()
        .filter(id__in=product_ids, tenant=tenant, status=True)
    )
    pmap = {p.id: p for p in products}
    missing = [pid for pid in product_ids if pid not in pmap]
    if missing:
        return Response({"detail": f"Products not found or inactive: {missing}"}, status=400)

    agg = (
        Inventory.objects
        .filter(
            tenant=tenant,
            product_id__in=product_ids,
            content_type_id=ct_branch.id,
            object_id=branch.id
        )
        .values("product_id")
        .annotate(total_qty=Sum("qty"))
    )
    total_map = {row["product_id"]: int(row["total_qty"] or 0) for row in agg}

    for pid, qty in wanted.items():
        total_available = total_map.get(pid, 0)
        if total_available < qty:
            p = pmap[pid]
            debug_rows = []
            if want_debug:
                debug_rows = list(
                    Inventory.objects.filter(
                        tenant=tenant, product_id=pid,
                        content_type_id=ct_branch.id, object_id=branch.id
                    ).values("id","qty","tenant_id","product_id","content_type_id","object_id")
                )
            return Response(
                {
                    "detail": "insufficient_stock",
                    "product_id": p.id,
                    "product_name": p.name,
                    "available": int(total_available),
                    "wanted": int(qty),
                    "branch_id": branch.id,
                    "ct_branch_id": ct_branch.id if want_debug else None,
                    "inv_rows": debug_rows if want_debug else None,
                },
                status=status.HTTP_409_CONFLICT
            )

    subtotal = Decimal("0.00")
    tax_sum = Decimal("0.00")
    resp_lines = []

    for pid, qty in wanted.items():
        p = pmap[pid]
        invs = (
            Inventory.objects
            .select_for_update()
            .only("id", "qty")
            .filter(
                tenant=tenant,
                product=p,
                content_type_id=ct_branch.id,
                object_id=branch.id
            )
            .order_by("id")
        )

        remaining = int(qty)
        for rec in invs:
            if remaining <= 0:
                break
            take = min(int(rec.qty), remaining)
            if take > 0:
                rec.qty = F("qty") - take
                rec.save(update_fields=["qty"])
                remaining -= take

        new_total = (
            Inventory.objects
            .filter(
                tenant=tenant,
                product=p,
                content_type_id=ct_branch.id,
                object_id=branch.id
            )
            .aggregate(s=Sum("qty"))["s"] or 0
        )

        unit_price = Decimal(p.price)
        line_subtotal = unit_price * qty
        line_tax = (line_subtotal * tax_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        line_total = (line_subtotal + line_tax).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        Sales.objects.create(
            tenant=tenant, branch=branch, warehouse=None, product=p,
            promotion_campaign=None, loyalty_benefits=None,
            unit_sold=qty, unit_price_snapshot=unit_price,
            discount_value_applied=Decimal("0.00"),
            tax_value_applied=line_tax, line_total=line_total,
            currency=currency, order_id=order_id, receipt_no=None,
            product_sku_snapshot=p.sku, product_name_snapshot=p.name,
            branch_name_snapshot=branch.name,
            created_by=agent_obj, modified_by=agent_obj,
        )

        resp_lines.append({
            "product_id": p.id,
            "sku": p.sku,
            "product_name": p.name,
            "qty": int(qty),
            "unit_price": f"{unit_price:.2f}",
            "tax": f"{line_tax:.2f}",
            "line_total": f"{line_total:.2f}",
            "new_stock": int(new_total),
        })

        subtotal += line_subtotal
        tax_sum  += line_tax

    total = (subtotal + tax_sum).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    payload = {
        "order_id": order_id,
        "subtotal": f"{subtotal:.2f}",
        "tax": f"{tax_sum:.2f}",
        "total": f"{total:.2f}",
        "currency": currency,
        "created_at": now_unix,
        "lines": resp_lines,
    }
    out = OrderCreatedSerializer(payload)
    if want_debug:
        # معلومة مساعدة
        extra = out.data | {"debug": {"branch_id": branch.id, "ct_branch_id": ct_branch.id}}
        return Response(extra, status=status.HTTP_201_CREATED)
    return Response(out.data, status=status.HTTP_201_CREATED)


# ============================================================
# KPI & Reports Endpoints
# ============================================================
@api_view(["GET"])
def sales_kpi_summary(request):
    tenant_id = request.GET.get("tenant", "Z0")
    from_ts = request.GET.get("from")
    to_ts = request.GET.get("to")

    qs = Sales.objects.filter(tenant_id=tenant_id)

    if from_ts and to_ts:
        try:
            from_ts = int(from_ts)
            to_ts = int(to_ts)
            qs = qs.filter(date_created__gte=from_ts, date_created__lte=to_ts)
        except:
            pass  # تجاهل التصفية لو فيها مشكلة

    total_sales = qs.aggregate(sum=Sum("line_total"))["sum"] or 0
    tax_collected = qs.aggregate(sum=Sum("tax_value_applied"))["sum"] or 0
    total_orders = qs.values("order_id").distinct().count()
    avg_order = (total_sales / total_orders) if total_orders > 0 else 0

    return Response({
        "total_sales": round(total_sales, 2),
        "total_orders": total_orders,
        "avg_order": round(avg_order, 2),
        "tax_collected": round(tax_collected, 2),
    })


@api_view(["GET"])
def revenue_over_time(request):
    tenant_id = request.GET.get("tenant", "Z0")
    days = int(request.GET.get("days", 7))

    now = int(time.time())
    from_timestamp = now - (days * 86400)

    # استرجع الصفوف خلال الفترة المطلوبة
    qs = (
        Sales.objects
        .filter(tenant_id=tenant_id, date_created__gte=from_timestamp)
        .values("date_created", "line_total")
    )

    # نجمع الإيرادات حسب كل يوم
    result = {}
    for row in qs:
        dt = datetime.utcfromtimestamp(row["date_created"]).strftime("%Y-%m-%d")
        result[dt] = result.get(dt, 0) + float(row["line_total"])

    # نرجع البيانات مرتبة
    chart_data = [{"day": day, "total": round(total, 2)} for day, total in sorted(result.items())]

    return Response({
        "days": days,
        "data": chart_data
    })


class ToDate(Func):
    function = 'DATE'
    template = "%(function)s(TO_TIMESTAMP(%(expressions)s))"


@api_view(['GET'])
def daily_revenue_chart(request):
    tenant = request.GET.get("tenant", "Z0")
    from_ts = int(request.GET.get("from", "0"))
    to_ts   = int(request.GET.get("to",   "9999999999"))

    # 1) اسحب السطور اللازمة فقط
    qs = (
        Sales.objects
        .filter(tenant_id=tenant, date_created__gte=from_ts, date_created__lte=to_ts)
        .values("date_created", "line_total")
    )

    # 2) اجمع حسب اليوم (بتوقيت UTC)
    per_day = defaultdict(Decimal)
    for row in qs:
        day = datetime.utcfromtimestamp(row["date_created"]).strftime("%Y-%m-%d")
        per_day[day] += Decimal(row["line_total"] or 0)

    # 3) ابنِ سلسلة الأيام واملأ الأيام الفارغة بـ 0
    start_day = datetime.utcfromtimestamp(from_ts).date()
    end_day   = datetime.utcfromtimestamp(to_ts).date()
    days = []
    data = []

    d = start_day
    while d <= end_day:
        key = d.strftime("%Y-%m-%d")
        days.append(key)
        data.append(float(per_day.get(key, Decimal("0"))))
        d += timedelta(days=1)

    # الناتج مناسب مباشرًا للشارت
    return Response({
        "days": days,                # ["2025-08-25", "2025-08-26", ...]
        "data": [{"day": k, "total": v} for k, v in zip(days, data)]
    })


@api_view(["GET"])
def top_products_and_categories(request):
    """
    GET /api/top-products-categories/?tenant=Z0&from=...&to=...&limit=5&order=desc
    - from/to اختياريّة. لو ما وجدت => نرجع كل البيانات.
    - لو timestamps كانت بالـ milliseconds بنحوّلها لثواني تلقائيًا.
    - order=desc (افتراضي) أو asc لترتيب حسب الإيراد.
    """
    tenant = request.GET.get("tenant", "Z0")

    # optional range
    from_raw = request.GET.get("from")
    to_raw   = request.GET.get("to")

    # limit + order
    try:
        limit = int(request.GET.get("limit", "5"))
    except Exception:
        limit = 5

    order = (request.GET.get("order", "desc") or "desc").lower()
    ordering = "-revenue" if order != "asc" else "revenue"

    # ابدأ بالفلترة حسب tenant فقط
    qs = Sales.objects.filter(tenant_id=tenant)

    # طبّق الفلترة الزمنية فقط لو مررت from/to
    def _norm_ts(v: str | None) -> int | None:
        if not v:
            return None
        try:
            ts = int(v)
            # لو واضح أنها milliseconds (13 digits تقريبًا) نقسم على 1000
            if ts > 10**12:  # 1,000,000,000,000
                ts //= 1000
            return ts
        except Exception:
            return None

    from_ts = _norm_ts(from_raw)
    to_ts   = _norm_ts(to_raw)

    if from_ts is not None:
        qs = qs.filter(date_created__gte=from_ts)
    if to_ts is not None:
        qs = qs.filter(date_created__lte=to_ts)

    # ----- Top Products -----
    prod_qs = (
        qs.values("product_id", "product_name_snapshot")
          .annotate(revenue=Sum("line_total"), qty=Sum("unit_sold"))
          .order_by(ordering)[:limit]
    )
    products = [
        {
            "product_id": row["product_id"],
            "name": row["product_name_snapshot"],
            "qty": int(row["qty"] or 0),
            "revenue": float(row["revenue"] or 0.0),
        }
        for row in prod_qs
    ]

    # ----- Top Categories -----
    cat_qs = (
        qs.values("product__category")
          .annotate(revenue=Sum("line_total"), qty=Sum("unit_sold"))
          .order_by(ordering)[:limit]
    )
    categories = [
        {
            "category": (row["product__category"] or "unknown"),
            "qty": int(row["qty"] or 0),
            "revenue": float(row["revenue"] or 0.0),
        }
        for row in cat_qs
    ]

    return Response({"products": products, "categories": categories})


@api_view(["GET"])
@cache_page(20)
def available_products_summary(request):
    tenant = request.GET.get("tenant", "Z0")
    # جِب الفرع من الكويري أو من settings
    try:
        branch_id = int(request.GET.get("branch", getattr(settings, "DEFAULT_BRANCH_ID", 1)))
    except Exception:
        branch_id = getattr(settings, "DEFAULT_BRANCH_ID", 1)

    q = (request.GET.get("q") or "").strip()

    # content_type للفرع
    ct_branch = ContentType.objects.get(app_label="products", model="branch")

    # اجمع مخزون الفرع بالـ product_id
    inv = (Inventory.objects
           .filter(tenant_id=tenant,
                   content_type_id=ct_branch.id,
                   object_id=branch_id)
           .values("product_id")
           .annotate(qty=Sum("qty"))
           .filter(qty__gt=0))

    qty_map = {row["product_id"]: row["qty"] for row in inv}

    # جيب المنتجات الموجودة في المخزون فقط
    qs = (Product.objects
          .filter(tenant_id=tenant, status=True, id__in=qty_map.keys()))

    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q) | Q(category__icontains=q))

    rows = (qs
            .order_by("name")
            .values("id", "name", "sku", "price", "category"))

    items = []
    for r in rows:
        items.append({
            "id": r["id"],
            "name": r["name"],
            "sku": r["sku"],
            "category": r["category"],
            "price": float(r["price"]),
            "stock": int(qty_map.get(r["id"], 0)),  # من Inventory (مخزون الفرع)
        })
    return Response({"items": items})


# ============================================================
# InvoiceView (Create + Printable HTML)
# ============================================================
class InvoiceView(APIView):
    permission_classes = [permissions.AllowAny]  # لاحقاً IsAuthenticated

    @transaction.atomic
    def post(self, request):
        """
        POST /api/invoices/
        { "order_id": "POS-...", "payment_method": "cash" }
        """
        data = request.data or {}
        order_id = data.get("order_id")
        if not order_id:
            return Response({"detail":"order_id is required"}, status=400)

        # نفس منطق الافتراضات المستخدم في OrdersView
        tenant_id = getattr(settings, "DEFAULT_TENANT_ID", "Z0")
        branch_id = getattr(settings, "DEFAULT_BRANCH_ID", 1)
        agent_id  = getattr(settings, "DEFAULT_AGENT_ID", None)
        payment_method = (data.get("payment_method") or "cash").lower()

        try:
            tenant = Tenant.objects.get(pk=tenant_id)
        except Tenant.DoesNotExist:
            return Response({"detail": f"Tenant {tenant_id} not found"}, status=400)

        branch = Branch.objects.filter(pk=branch_id).first()
        if branch is None:
            return Response({"detail": f"Branch {branch_id} not found"}, status=400)

        agent = None
        if agent_id is not None:
            agent = Agent.objects.filter(pk=agent_id).first()

        try:
            inv = create_invoice_for_order(order_id, tenant=tenant, branch=branch, agent=agent,
                                           payment_method=payment_method)
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)

        return Response({
            "invoice_no": inv.invoice_no,
            "order_id": inv.order_id,
            "currency": inv.currency,
            "subtotal": f"{inv.subtotal:.2f}",
            "tax": f"{inv.tax:.2f}",
            "total": f"{inv.total:.2f}",
            "created_at": inv.date_created,
            "print_url": f"/api/invoices/{inv.invoice_no}/html",
        }, status=201)

    def get(self, request, invoice_no, fmt="html"):
        """
        GET /api/invoices/<invoice_no>/html  -> صفحة HTML للطباعة
        """
        inv = (Invoice.objects
               .select_related("tenant","branch","created_by")
               .prefetch_related("lines")
               .get(invoice_no=invoice_no))

        html = render_to_string("invoice/receipt.html", {"invoice": inv, "lines": inv.lines.all()})
        return HttpResponse(html)

@api_view(["POST"])
def inventory_receive(request):
    """
    POST /api/inventory/receive/
    {
      "tenant": "Z0",            // اختياري: لو ما أرسلته ناخذ من settings.DEFAULT_TENANT_ID
      "warehouse_id": 7,
      "product_id": 42,
      "qty": 100,
      "idempotency_key": "optional-uuid"
    }
    """
    data = request.data or {}
    tenant_id = data.get("tenant") or getattr(settings, "DEFAULT_TENANT_ID", "Z0")
    warehouse_id = data.get("warehouse_id")
    product_id = data.get("product_id")
    qty = int(data.get("qty") or 0)
    idem = data.get("idempotency_key")

    if not warehouse_id or not product_id or qty <= 0:
        return Response({"detail": "warehouse_id, product_id, qty are required"}, status=400)

    try:
        tenant = Tenant.objects.get(id=tenant_id)
    except Tenant.DoesNotExist:
        return Response({"detail": f"Tenant {tenant_id} not found"}, status=400)

    warehouse = Warehouse.objects.filter(id=warehouse_id).first()
    if not warehouse:
        return Response({"detail": f"Warehouse {warehouse_id} not found"}, status=400)

    product = Product.objects.filter(id=product_id, tenant=tenant, status=True).first()
    if not product:
        return Response({"detail": f"Product {product_id} not found or inactive"}, status=400)

    # agent: من المستخدم أو من الإعدادات الإفتراضية
    agent = None
    req_agent_id = getattr(getattr(request.user, "agent", None), "pk", None)
    if req_agent_id:
        agent = Agent.objects.filter(pk=req_agent_id).first()
    if agent is None:
        default_agent = getattr(settings, "DEFAULT_AGENT_ID", None)
        if default_agent:
            agent = Agent.objects.filter(pk=default_agent).first()
    if agent is None:
        agent = Agent.objects.first()

    try:
        res = receive_to_warehouse(
            tenant=tenant, product=product, warehouse=warehouse,
            qty=qty, agent=agent, idempotency_key=idem
        )
        return Response({
            "movement_id": res.movement_id,
            "idempotency_key": res.idempotency_key,
            "onhand_after": res.onhand_after,
            "warehouse_id": warehouse.id,
            "product_id": product.id,
        }, status=status.HTTP_201_CREATED)
    except StockError as e:
        return Response({"detail": str(e)}, status=400)




# ==== Stock Movements API (Warehouse & Branch) ====
from .serializers import (
    StockReceiveSerializer, StockDispatchSerializer, BranchReceiveSerializer
)
from .services import (
    receive_to_warehouse, dispatch_to_branch, receive_from_warehouse, StockError
)

class StockReceiveWarehouseView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        s = StockReceiveSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        tenant_id = getattr(settings, "DEFAULT_TENANT_ID", "Z0")
        agent_id  = getattr(settings, "DEFAULT_AGENT_ID", 0)

        tenant = Tenant.objects.get(id=tenant_id)
        agent  = Agent.objects.get(id=agent_id)
        product = Product.objects.get(id=data["product_id"], tenant=tenant)
        warehouse = Warehouse.objects.get(id=data["warehouse_id"])

        try:
            res = receive_to_warehouse(
                tenant=tenant, product=product, warehouse=warehouse,
                qty=data["qty"], agent=agent,
                idempotency_key=(str(data["idempotency_key"]) if data.get("idempotency_key") else None),
                notes=data.get("notes") or ""
            )
        except StockError as e:
            return Response({"detail": str(e)}, status=400)

        return Response({
            "movement_id": res.movement_id,
            "idempotency_key": res.idempotency_key,
            "warehouse_onhand": res.warehouse_onhand,
        }, status=201)


class StockDispatchToBranchView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        s = StockDispatchSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        tenant_id = getattr(settings, "DEFAULT_TENANT_ID", "Z0")
        agent_id  = getattr(settings, "DEFAULT_AGENT_ID", 0)

        tenant = Tenant.objects.get(id=tenant_id)
        agent  = Agent.objects.get(id=agent_id)
        product = Product.objects.get(id=data["product_id"], tenant=tenant)
        warehouse = Warehouse.objects.get(id=data["warehouse_id"])
        branch    = Branch.objects.get(id=data["branch_id"])

        try:
            res = dispatch_to_branch(
                tenant=tenant, product=product, warehouse=warehouse, branch=branch,
                qty=data["qty"], agent=agent,
                idempotency_key=(str(data["idempotency_key"]) if data.get("idempotency_key") else None),
                notes=data.get("notes") or ""
            )
        except StockError as e:
            return Response({"detail": str(e)}, status=400)

        return Response({
            "movement_id": res.movement_id,
            "idempotency_key": res.idempotency_key,
            "warehouse_onhand": res.warehouse_onhand,
        }, status=201)


class BranchReceiveFromWarehouseView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        s = BranchReceiveSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        tenant_id = getattr(settings, "DEFAULT_TENANT_ID", "Z0")
        agent_id  = getattr(settings, "DEFAULT_AGENT_ID", 0)

        tenant = Tenant.objects.get(id=tenant_id)
        agent  = Agent.objects.get(id=agent_id)
        product = Product.objects.get(id=data["product_id"], tenant=tenant)
        branch  = Branch.objects.get(id=data["branch_id"])

        try:
            res = receive_from_warehouse(
                tenant=tenant, product=product, branch=branch,
                qty=data["qty"], agent=agent,
                idempotency_key=(str(data["idempotency_key"]) if data.get("idempotency_key") else None),
                notes=data.get("notes") or ""
            )
        except StockError as e:
            return Response({"detail": str(e)}, status=400)

        return Response({
            "movement_id": res.movement_id,
            "idempotency_key": res.idempotency_key,
            "branch_onhand": res.branch_onhand,
        }, status=201)
@api_view(["GET"])
def warehouse_products_summary(request):
    """
    GET /api/warehouse-products-summary/?tenant=Z0[&warehouse=7][&q=...][&hide_zero=1]
    يعيد items = [{id,name,sku,category,price,stock}]
    stock = on-hand في المستودع المحدد (أو كل المستودعات)
    """
    tenant = request.GET.get("tenant", "Z0")
    warehouse_id = request.GET.get("warehouse")  # اختياري
    q = (request.GET.get("q") or "").strip()
    hide_zero = request.GET.get("hide_zero") in ("1", "true", "yes")

    ct_wh = ContentType.objects.get(app_label="products", model="warehouse")

    inv = Inventory.objects.filter(tenant_id=tenant, content_type_id=ct_wh.id)
    if warehouse_id:
        inv = inv.filter(object_id=int(warehouse_id))

    # ما نفلتر بـ qty__gt=0 — نرجّع حتى الصفر
    agg = inv.values("product_id").annotate(qty=Coalesce(Sum("qty"), 0))
    if hide_zero:
        agg = agg.filter(qty__gt=0)

    qty_map = {row["product_id"]: max(0, int(row["qty"] or 0)) for row in agg}

    qs = Product.objects.filter(tenant_id=tenant, id__in=qty_map.keys(), status=True)
    if q:
        qs = qs.filter(
            Q(name__icontains=q) | Q(sku__icontains=q) | Q(category__icontains=q)
        )

    rows = qs.order_by("name").values("id", "name", "sku", "price", "category")

    items = []
    for r in rows:
        items.append({
            "id": r["id"],
            "name": r["name"],
            "sku": r["sku"],
            "category": r["category"],
            "price": float(r["price"] or 0),
            "stock": int(qty_map.get(r["id"], 0)),  # الآن تظهر 0 بدل الاختفاء
        })
    return Response({"items": items})



# --- أعلى الملف (إضافات imports) ---
import uuid
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny

from .models import (
    Product, Sales, Tenant, Branch, Agent, Invoice, Inventory,
    Warehouse, StockMovement,   # ← أضفنا هذولا
)
from .services import (       # ← نستعمل خدمات المخزون
    receive_to_warehouse, dispatch_to_branch, receive_from_warehouse, StockError
)

# --- مساعدات عامة لهذا القسم ---
def _uuid_or_none(v):
    try:
        if not v:
            return None
        return str(uuid.UUID(str(v)))
    except Exception:
        return None

def _get_tenant_agent_branch(request):
    tenant_id = getattr(settings, "DEFAULT_TENANT_ID", "Z0")
    branch_id = getattr(settings, "DEFAULT_BRANCH_ID", None)
    agent_id  = getattr(settings, "DEFAULT_AGENT_ID", None)

    # لو المستخدم له Agent مربوط، استعمله
    req_agent = getattr(getattr(request.user, "agent", None), "pk", None)
    if req_agent is not None:
        agent_id = req_agent

    # جلب الكيانات
    tenant = Tenant.objects.get(pk=tenant_id)

    agent = None
    if agent_id is not None:
        agent = Agent.objects.filter(pk=agent_id).first()
    if agent is None:
        agent = Agent.objects.first()

    branch = None
    if branch_id:
        branch = Branch.objects.filter(pk=branch_id).first()

    return tenant, agent, branch

# ============ حركات المخزون ============

@api_view(["POST"])
@permission_classes([AllowAny])
@transaction.atomic
def stock_receive_warehouse(request):
    """
    POST /api/stock/receive-warehouse/
    { "product_id": 42, "qty": 100, "warehouse_id": 7 (اختياري), "idempotency_key": "..." (اختياري), "notes": "" }
    """
    data = request.data or {}
    try:
        product_id = int(data.get("product_id"))
        qty = int(data.get("qty"))
    except Exception:
        return Response({"detail": "product_id and qty are required (ints)."}, status=400)

    idem = _uuid_or_none(data.get("idempotency_key"))
    notes = (data.get("notes") or "").strip()

    tenant, agent, _ = _get_tenant_agent_branch(request)
    try:
        product = Product.objects.get(pk=product_id, tenant=tenant, status=True)
    except Product.DoesNotExist:
        return Response({"detail": f"Product {product_id} not found or inactive."}, status=400)

    # مستودع: عندكم واحد فقط؛ خذه أول واحد أو احترم warehouse_id إن مرّ
    wh = None
    if data.get("warehouse_id"):
        wh = Warehouse.objects.filter(pk=int(data["warehouse_id"])).first()
    if wh is None:
        wh = Warehouse.objects.first()
    if wh is None:
        return Response({"detail": "No warehouse found."}, status=400)

    try:
        r = receive_to_warehouse(tenant=tenant, product=product, warehouse=wh,
                                 qty=qty, agent=agent, idempotency_key=idem, notes=notes)
    except StockError as e:
        return Response({"detail": str(e)}, status=400)

    return Response({
        "movement_id": r.movement_id,
        "idempotency_key": r.idempotency_key,
        "warehouse_id": wh.id,
        "warehouse_onhand": r.warehouse_onhand,
        "qty": qty,
        "status": "ok",
    }, status=201)


@api_view(["POST"])
@permission_classes([AllowAny])
@transaction.atomic
def stock_dispatch_to_branch(request):
    """
    POST /api/stock/dispatch-to-branch/
    { "product_id": 42, "branch_id": 39, "qty": 20, "warehouse_id": 7 (اختياري), "idempotency_key": "..." (اختياري), "notes": "" }
    """
    data = request.data or {}
    try:
        product_id = int(data.get("product_id"))
        branch_id = int(data.get("branch_id"))
        qty = int(data.get("qty"))
    except Exception:
        return Response({"detail": "product_id, branch_id, qty are required (ints)."}, status=400)

    idem = _uuid_or_none(data.get("idempotency_key"))
    notes = (data.get("notes") or "").strip()

    tenant, agent, _ = _get_tenant_agent_branch(request)
    try:
        product = Product.objects.get(pk=product_id, tenant=tenant, status=True)
    except Product.DoesNotExist:
        return Response({"detail": f"Product {product_id} not found or inactive."}, status=400)

    branch = Branch.objects.filter(pk=branch_id).first()
    if branch is None:
        return Response({"detail": f"Branch {branch_id} not found."}, status=400)

    wh = None
    if data.get("warehouse_id"):
        wh = Warehouse.objects.filter(pk=int(data["warehouse_id"])).first()
    if wh is None:
        wh = Warehouse.objects.first()
    if wh is None:
        return Response({"detail": "No warehouse found."}, status=400)

    try:
        r = dispatch_to_branch(tenant=tenant, product=product,
                               warehouse=wh, branch=branch, qty=qty,
                               agent=agent, idempotency_key=idem, notes=notes)
    except StockError as e:
        return Response({"detail": str(e)}, status=400)

    return Response({
        "movement_id": r.movement_id,
        "idempotency_key": r.idempotency_key,
        "warehouse_id": wh.id,
        "branch_id": branch.id,
        "warehouse_onhand": r.warehouse_onhand,
        "qty": qty,
        "status": "ok",
    }, status=201)


@api_view(["POST"])
@permission_classes([AllowAny])
@transaction.atomic
def stock_receive_from_warehouse(request):
    """
    POST /api/stock/receive-from-warehouse/
    { "product_id": 42, "branch_id": 39, "qty": 20, "idempotency_key": "..." (اختياري), "notes": "" }
    """
    data = request.data or {}
    try:
        product_id = int(data.get("product_id"))
        branch_id = int(data.get("branch_id"))
        qty = int(data.get("qty"))
    except Exception:
        return Response({"detail": "product_id, branch_id, qty are required (ints)."}, status=400)

    idem = _uuid_or_none(data.get("idempotency_key"))
    notes = (data.get("notes") or "").strip()

    tenant, agent, _ = _get_tenant_agent_branch(request)
    try:
        product = Product.objects.get(pk=product_id, tenant=tenant, status=True)
    except Product.DoesNotExist:
        return Response({"detail": f"Product {product_id} not found or inactive."}, status=400)

    branch = Branch.objects.filter(pk=branch_id).first()
    if branch is None:
        return Response({"detail": f"Branch {branch_id} not found."}, status=400)

    try:
        r = receive_from_warehouse(tenant=tenant, product=product,
                                   branch=branch, qty=qty,
                                   agent=agent, idempotency_key=idem, notes=notes)
    except StockError as e:
        return Response({"detail": str(e)}, status=400)

    return Response({
        "movement_id": r.movement_id,
        "idempotency_key": r.idempotency_key,
        "branch_id": branch.id,
        "branch_onhand": r.branch_onhand,
        "qty": qty,
        "status": "ok",
    }, status=201)


@api_view(["GET"])
@permission_classes([AllowAny])
def stock_movements(request):
    """
    GET /api/stock/movements/?tenant=Z0&product_id=42&limit=50
    يرجّع آخر الحركات لهذا التينانت (مع إمكانية فلترة المنتج)
    """
    tenant_id = request.GET.get("tenant", getattr(settings, "DEFAULT_TENANT_ID", "Z0"))
    limit = int(request.GET.get("limit", "50"))
    product_id = request.GET.get("product_id")

    qs = StockMovement.objects.filter(tenant_id=tenant_id).order_by("-id")
    if product_id:
        qs = qs.filter(product_id=int(product_id))

    rows = list(qs.values(
        "id", "movement_type", "status", "qty", "idempotency_key",
        "from_content_type_id", "from_object_id",
        "to_content_type_id", "to_object_id",
        "date_created"
    )[:limit])

    # نحوّل UUID لـ str
    for r in rows:
        r["idempotency_key"] = str(r["idempotency_key"]) if r["idempotency_key"] else None

    return Response({"rows": rows})



# products/views.py  (أضِف الاستيرادات في أعلى الملف)
import uuid
import time
from decimal import Decimal
from django.db import transaction
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status, permissions
from django.template.loader import render_to_string
from django.http import HttpResponse
from django.conf import settings

from .models import StockTransfer, Tenant, Product, Warehouse, Branch, Agent
from .services import dispatch_to_branch, receive_from_warehouse, StockError
# ------------------------------------------------------------

def _now_unix() -> int:
    return int(time.time())

def _get_agent(request):
    agent_pk = getattr(getattr(request.user, "agent", None), "pk", None)
    if agent_pk:
        return Agent.objects.filter(pk=agent_pk).first()
    default_agent = getattr(settings, "DEFAULT_AGENT_ID", None)
    if default_agent is not None:
        return Agent.objects.filter(pk=default_agent).first()
    return Agent.objects.first()

@api_view(["POST", "GET"])
@transaction.atomic
def transfers(request):
    """
    POST /api/transfers/
      body: { tenant?, product_id, warehouse_id?, branch_id, qty, idempotency_key? }
      - ينفّذ Dispatch ثم Receive داخل معاملة واحدة
      - ينشئ سجل StockTransfer
    GET  /api/transfers/?tenant=Z0&from=...&to=...&product=...&branch=...&page=1&limit=20
      - يرجع قائمة التحويلات (أحدث أولاً)
    """
    if request.method == "GET":
        tenant = request.GET.get("tenant", getattr(settings, "DEFAULT_TENANT_ID", "Z0"))
        try:
            from_ts = int(request.GET.get("from") or 0)
        except:
            from_ts = 0
        try:
            to_ts = int(request.GET.get("to") or 9999999999)
        except:
            to_ts = 9999999999

        qs = (StockTransfer.objects
              .select_related("product","warehouse","branch","created_by")
              .filter(tenant_id=tenant, date_created__gte=from_ts, date_created__lte=to_ts)
              .order_by("-date_created","-id"))

        product_id = request.GET.get("product")
        branch_id  = request.GET.get("branch")
        if product_id:
            qs = qs.filter(product_id=int(product_id))
        if branch_id:
            qs = qs.filter(branch_id=int(branch_id))

        # ترقيم بسيط
        try:
            page  = max(1, int(request.GET.get("page", "1")))
        except:
            page = 1
        try:
            limit = max(1, min(100, int(request.GET.get("limit", "20"))))
        except:
            limit = 20

        start = (page - 1) * limit
        rows = qs[start:start+limit]

        data = []
        for r in rows:
            creator = r.created_by
            creator_label = None
            if creator:
                creator_label = (
                        getattr(creator, "name", None)
                        or getattr(creator, "full_name", None)
                        or getattr(creator, "username", None)
                        or getattr(creator, "email", None)
                        or str(creator)
                )

            data.append({
                "transfer_id": str(r.transfer_id),
                "product_id": r.product_id,
                "product_name": r.product.name,
                "warehouse_id": r.warehouse_id,
                "warehouse_name": r.warehouse.name,
                "branch_id": r.branch_id,
                "branch_name": r.branch.name,
                "qty": int(r.qty),
                "created_by": creator_label,  # ← هنا
                "created_at": int(r.date_created),
                "status": r.status,
                "print_url": f"/api/transfers/{r.transfer_id}/html",
            })
        return Response({
            "page": page,
            "limit": limit,
            "count": qs.count(),
            "items": data,
        })

    # ------- POST: إنشاء تحويل -------
    body = request.data or {}
    tenant_id = body.get("tenant") or getattr(settings, "DEFAULT_TENANT_ID", "Z0")
    product_id = body.get("product_id")
    branch_id  = body.get("branch_id") or getattr(settings, "DEFAULT_BRANCH_ID", None)
    warehouse_id = body.get("warehouse_id") or getattr(settings, "DEFAULT_WAREHOUSE_ID", None)
    qty = int(body.get("qty") or 0)

    if not product_id or not branch_id or not qty:
        return Response({"detail": "product_id, branch_id, qty are required"}, status=400)

    try:
        tenant = Tenant.objects.get(pk=tenant_id)
    except Tenant.DoesNotExist:
        return Response({"detail": f"Tenant {tenant_id} not found"}, status=400)

    product = Product.objects.filter(pk=product_id, tenant=tenant, status=True).first()
    if product is None:
        return Response({"detail": f"Product {product_id} not found or inactive"}, status=400)

    branch = Branch.objects.filter(pk=branch_id).first()
    if branch is None:
        return Response({"detail": f"Branch {branch_id} not found"}, status=400)

    if warehouse_id is None:
        # لو ما عندك إلا مستودع واحد، خُذه first()
        wh = Warehouse.objects.first()
        if wh is None:
            return Response({"detail":"No warehouse found"}, status=400)
    else:
        wh = Warehouse.objects.filter(pk=warehouse_id).first()
        if wh is None:
            return Response({"detail": f"Warehouse {warehouse_id} not found"}, status=400)

    agent = _get_agent(request)

    # توليد transfer_id موحّد، ونستخدمه لعمل idempotency متفرّع
    tid = uuid.uuid4()
    key_dispatch = uuid.uuid5(tid, "OUT")  # UUID صالح مشتق من transfer_id
    key_receive = uuid.uuid5(tid, "IN")  # UUID صالح مشتق من transfer_id

    try:
        mv1 = dispatch_to_branch(
            tenant=tenant, product=product, warehouse=wh, branch=branch,
            qty=qty, agent=agent, idempotency_key=key_dispatch
        )
        mv2 = receive_from_warehouse(
            tenant=tenant, product=product, branch=branch,
            qty=qty, agent=agent, idempotency_key=key_receive
        )
    except StockError as e:
        # في حال نفاد مخزون المستودع
        # services غالباً ترفع StockError وتحتوي available وغيرها (لو ما توفر نرجّع رسالة عامة)
        return Response({"detail":"insufficient_stock"}, status=status.HTTP_409_CONFLICT)

    tr = StockTransfer.objects.create(
        tenant=tenant, product=product, warehouse=wh, branch=branch,
        qty=qty, transfer_id=tid, created_by=agent, date_created=_now_unix(),
        status="POSTED",
        dispatch_movement_id=getattr(mv1, "id", None),
        receive_movement_id=getattr(mv2, "id", None),
    )

    return Response({
        "transfer_id": str(tr.transfer_id),
        "product_id": product.id,
        "branch_id": branch.id,
        "warehouse_id": wh.id,
        "qty": qty,
        "warehouse_onhand": getattr(mv1, "warehouse_onhand", None),
        "branch_onhand": getattr(mv2, "branch_onhand", None),
        "print_url": f"/api/transfers/{tr.transfer_id}/html",
        "created_at": tr.date_created,
    }, status=status.HTTP_201_CREATED)


def transfer_receipt_html(request, transfer_id, fmt="html"):
    """
    GET /api/transfers/<transfer_id>/html
    سند تحويل للطباعة (قالب حراري بسيط)
    """
    tr = (StockTransfer.objects
          .select_related("tenant","product","warehouse","branch","created_by")
          .get(transfer_id=transfer_id))

    html = render_to_string("transfer/receipt.html", {"tr": tr})
    return HttpResponse(html)
