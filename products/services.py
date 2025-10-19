# products/services.py

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional, Tuple

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import F, Max

from .models import (
    # فواتير
    Invoice, InvoiceLine, Sales,
    # كيانات أساسية
    Tenant, Branch, Agent, Product, Warehouse, Inventory, StockMovement,
)

def next_invoice_no(branch_id: int) -> str:
    today = datetime.utcnow().strftime("%Y%m%d")
    prefix = f"INV-{branch_id}-{today}-"
    last = (
        Invoice.objects
        .filter(branch_id=branch_id, invoice_no__startswith=prefix)
        .aggregate(mx=Max("invoice_no"))
        .get("mx")
    )
    if not last:
        return f"{prefix}0001"
    seq = int(last.rsplit("-", 1)[-1]) + 1
    return f"{prefix}{seq:04d}"

@transaction.atomic
def create_invoice_for_order(order_id: str, *, tenant: Tenant, branch: Branch, agent: Agent | None,
                             payment_method: str = "cash", tax_rate: Decimal | None = None) -> Invoice:
    # لو فيه فاتورة جاهزة لنفس الطلب، رجّعها (idempotent)
    existing = Invoice.objects.filter(tenant=tenant, branch=branch, order_id=order_id).first()
    if existing:
        return existing

    rows = list(
        Sales.objects.select_for_update()
        .filter(tenant=tenant, branch=branch, order_id=order_id)
    )
    if not rows:
        raise ValueError(f"No sales rows for order_id={order_id}")

    currency = rows[0].currency
    subtotal = sum((r.unit_price_snapshot * r.unit_sold for r in rows), Decimal("0.00"))
    tax      = sum((r.tax_value_applied      for r in rows), Decimal("0.00"))
    total    = sum((r.line_total             for r in rows), Decimal("0.00"))

    inv = Invoice.objects.create(
        tenant=tenant, branch=branch,
        invoice_no=next_invoice_no(branch.id),
        order_id=order_id,
        currency=currency,
        payment_method=payment_method,
        subtotal=subtotal.quantize(Decimal("0.01")),
        tax=tax.quantize(Decimal("0.01")),
        total=total.quantize(Decimal("0.01")),
        tax_rate=(tax_rate if tax_rate is not None else Decimal("0.10")),
        created_by=agent, modified_by=agent,
    )

    for r in rows:
        InvoiceLine.objects.create(
            invoice=inv, product=r.product,
            name=r.product_name_snapshot, sku=r.product_sku_snapshot,
            qty=r.unit_sold, unit_price=r.unit_price_snapshot,
            tax=r.tax_value_applied, line_total=r.line_total,
        )

    # (مفيد) اربط رقم الفاتورة في sales.receipt_no
    Sales.objects.filter(tenant=tenant, branch=branch, order_id=order_id).update(receipt_no=inv.invoice_no)
    return inv


# ================== Inventory Stock Services (Step 1) ==================


class StockError(Exception):
    pass

@dataclass
class MoveResult:
    movement_id: int
    idempotency_key: str
    onhand_after: int              # رصيد OnHand للطرف المتأثر
    warehouse_onhand: Optional[int] = None
    branch_onhand: Optional[int] = None

def _ct_and_id(target) -> Tuple[ContentType, int]:
    if isinstance(target, Warehouse) or isinstance(target, Branch):
        return ContentType.objects.get_for_model(target.__class__), target.pk
    raise StockError("target must be Warehouse or Branch instance")

def _get_or_create_inv(tenant: Tenant, product: Product, target) -> Inventory:
    ct, oid = _ct_and_id(target)
    inv, _ = Inventory.objects.get_or_create(
        tenant=tenant, product=product, content_type=ct, object_id=oid,
        defaults={"qty": 0, "name": product.name, "unit": 1, "status": "", "supply_chain": ""},
    )
    return inv

def _ensure_tenant(obj_tenant: Tenant, *objs):
    for o in objs:
        if hasattr(o, "tenant_id"):
            tid = getattr(o, "tenant_id")
            if tid and tid != obj_tenant.id:
                raise StockError("Tenant mismatch")

def _create_or_get_movement(
    *,
    tenant: Tenant,
    product: Product,
    movement_type: str,
    qty: int,
    created_by: Agent,
    modified_by: Agent,
    from_target=None,
    to_target=None,
    idempotency_key: Optional[str] = None,
    notes: Optional[str] = None,
    status: str = StockMovement.POSTED,
) -> StockMovement:
    kwargs = {
        "tenant": tenant,
        "product": product,
        "movement_type": movement_type,
        "qty": qty,
        "created_by": created_by,
        "modified_by": modified_by,
        "status": status,
        "notes": notes or "",
    }
    if from_target is not None:
        ct, oid = _ct_and_id(from_target)
        kwargs.update({"from_content_type": ct, "from_object_id": oid})
    if to_target is not None:
        ct, oid = _ct_and_id(to_target)
        kwargs.update({"to_content_type": ct, "to_object_id": oid})

    if idempotency_key:
        obj, created = StockMovement.objects.get_or_create(
            idempotency_key=idempotency_key, defaults=kwargs
        )
        if not created:
            return obj
        return obj
    else:
        return StockMovement.objects.create(**kwargs)

@transaction.atomic
def receive_to_warehouse(
    *, tenant: Tenant, product: Product, warehouse: Warehouse,
    qty: int, agent: Agent, idempotency_key: Optional[str] = None, notes: str = ""
) -> MoveResult:
    if qty <= 0:
        raise StockError("qty must be > 0")
    _ensure_tenant(tenant, product)

    inv = (
        Inventory.objects.select_for_update()
        .filter(tenant=tenant, product=product,
                content_type=ContentType.objects.get_for_model(Warehouse),
                object_id=warehouse.id)
        .first()
    ) or _get_or_create_inv(tenant, product, warehouse)

    inv.qty = F("qty") + qty
    inv.save(update_fields=["qty"])
    inv.refresh_from_db(fields=["qty"])

    mv = _create_or_get_movement(
        tenant=tenant, product=product,
        movement_type=StockMovement.INBOUND_RECEIPT,
        qty=qty, created_by=agent, modified_by=agent,
        from_target=None, to_target=warehouse,
        idempotency_key=idempotency_key, notes=notes,
    )
    return MoveResult(mv.id, str(mv.idempotency_key), onhand_after=int(inv.qty),
                      warehouse_onhand=int(inv.qty))

@transaction.atomic
def dispatch_to_branch(
    *, tenant: Tenant, product: Product, warehouse: Warehouse, branch: Branch,
    qty: int, agent: Agent, idempotency_key: Optional[str] = None, notes: str = ""
) -> MoveResult:
    if qty <= 0:
        raise StockError("qty must be > 0")
    _ensure_tenant(tenant, product)

    wh_inv = (
        Inventory.objects.select_for_update()
        .filter(tenant=tenant, product=product,
                content_type=ContentType.objects.get_for_model(Warehouse),
                object_id=warehouse.id)
        .first()
    ) or _get_or_create_inv(tenant, product, warehouse)

    if wh_inv.qty < qty:
        raise StockError(f"insufficient on-hand in warehouse: have {wh_inv.qty}, need {qty}")

    wh_inv.qty = F("qty") - qty
    wh_inv.save(update_fields=["qty"])
    wh_inv.refresh_from_db(fields=["qty"])

    mv = _create_or_get_movement(
        tenant=tenant, product=product,
        movement_type=StockMovement.DISPATCH_TO_BRANCH,
        qty=qty, created_by=agent, modified_by=agent,
        from_target=warehouse, to_target=branch,
        idempotency_key=idempotency_key, notes=notes,
    )
    return MoveResult(mv.id, str(mv.idempotency_key), onhand_after=int(wh_inv.qty),
                      warehouse_onhand=int(wh_inv.qty))

@transaction.atomic
def receive_from_warehouse(
    *, tenant: Tenant, product: Product, branch: Branch,
    qty: int, agent: Agent, idempotency_key: Optional[str] = None, notes: str = ""
) -> MoveResult:
    if qty <= 0:
        raise StockError("qty must be > 0")
    _ensure_tenant(tenant, product)

    br_inv = (
        Inventory.objects.select_for_update()
        .filter(tenant=tenant, product=product,
                content_type=ContentType.objects.get_for_model(Branch),
                object_id=branch.id)
        .first()
    ) or _get_or_create_inv(tenant, product, branch)

    br_inv.qty = F("qty") + qty
    br_inv.save(update_fields=["qty"])
    br_inv.refresh_from_db(fields=["qty"])

    mv = _create_or_get_movement(
        tenant=tenant, product=product,
        movement_type=StockMovement.RECEIVE_FROM_WAREHOUSE,
        qty=qty, created_by=agent, modified_by=agent,
        from_target=None, to_target=branch,
        idempotency_key=idempotency_key, notes=notes,
    )
    return MoveResult(mv.id, str(mv.idempotency_key), onhand_after=int(br_inv.qty),
                      branch_onhand=int(br_inv.qty))
# ================== /Inventory Stock Services ==================
