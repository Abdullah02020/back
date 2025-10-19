import time
import uuid
from django.db import models
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.core.exceptions import ValidationError
class Tenant(models.Model):
    id = models.CharField(max_length=60, primary_key=True)
    name = models.CharField(max_length=60, unique=True, null=True, blank=True)
    date_created = models.BigIntegerField(null=True, blank=True)
    last_modified = models.BigIntegerField(editable=False)
    modified_by = models.IntegerField(null=True, blank=True)
    status = models.BooleanField(default=False)
    created_by = models.IntegerField(null=True, blank=True)
    domain=models.CharField(max_length=100, null=True, blank=True)
    email=models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        db_table = "tenants"
        unique_together = ("name", "domain", 'email')
        indexes = [
            models.Index(fields=["status"], name="idx_tenants_status"),
            models.Index(fields=["last_modified"], name="idx_tenants_last_modified"),
        ]

    def save(self, *args, **kwargs):
        # always use current UTC time in seconds
        self.last_modified = int(time.time())
        # if new object, set date_created too
        if not self.date_created:
            self.date_created = self.last_modified
        super().save(*args, **kwargs)

class Division(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=60)
    tenant = models.ForeignKey("Tenant", to_field="id", db_column="tenant", on_delete=models.CASCADE)
    status = models.IntegerField()
    supervisor = models.IntegerField()
    last_modified = models.BigIntegerField(null=True, blank=True)
    modified_by = models.IntegerField(editable=False)
    no_reply_email = models.CharField(max_length=100, null=True, blank=True)
    contact_us_email = models.CharField(max_length=100, null=True, blank=True)
    date_created=models.BigIntegerField(editable=False)

    class Meta:
        db_table = "division"
        unique_together = ("name", "tenant")
        indexes = [
            models.Index(fields=["tenant"], name="idx_division_tenant"),
            models.Index(fields=["status"], name="idx_division_status"),
            models.Index(fields=["supervisor"], name="idx_division_supervisor"),
            models.Index(fields=["last_modified"], name="idx_division_last_modified"),
        ]

    def save(self, *args, **kwargs):
        # always use current UTC time in seconds
        self.last_modified = int(time.time())
        # if new object, set date_created too
        if not self.date_created:
            self.date_created = self.last_modified
        super().save(*args, **kwargs)

class Agent(models.Model):
    id = models.AutoField(primary_key=True)
    pr_key = models.TextField(null=True, blank=True)
    pr_exp = models.TextField(null=True, blank=True)
    app_role_assignment_id = models.TextField(null=True, blank=True)
    service_principal_id = models.TextField(null=True, blank=True)
    role_id = models.TextField(null=True, blank=True)
    user_id = models.TextField(null=True, blank=True)
    account_status = models.CharField(max_length=20, choices=[("Invitation", "Invitation"), ("Active", "Active"), ('Deactivated', 'Deactivated')],null=True, blank=True)
    zaad_code = models.TextField(null=True, blank=True)
    username = models.TextField(null=True, blank=True)
    user_avatar = models.TextField(null=True, blank=True)
    nonce = models.TextField(null=True, blank=True)
    pp_exp = models.BigIntegerField(null=True, blank=True)
    created_by = models.IntegerField(null=True, blank=True)
    date_created = models.BigIntegerField(null=True, blank=True)
    default_landing_page = models.TextField(null=True, blank=True)
    active_team = models.TextField(null=True, blank=True)
    default_expand_mode = models.TextField(null=True, blank=True)
    phone_number = models.TextField(null=True, blank=True)
    full_name = models.TextField(null=True, blank=True)
    account_type = models.CharField(max_length=20)
    account_role = models.IntegerField(null=True, blank=True)
    division = models.ForeignKey("Division", on_delete=models.CASCADE, null=True, blank=True, db_column="division")
    modified_by = models.IntegerField(null=True, blank=True)
    last_modified = models.BigIntegerField(editable=False)
    first_name = models.TextField(null=True, blank=True)
    last_name = models.TextField(null=True, blank=True)
    pb_key = models.TextField(null=True, blank=True)
    password = models.TextField(null=True, blank=True)
    password_status = models.IntegerField(default=0)
    tenant = models.ForeignKey("Tenant", to_field="id", db_column="tenant", on_delete=models.CASCADE)
    one_time_pass_exp=models.BigIntegerField(null=True, blank=True)
    one_time_pass = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "agent"
        unique_together = ("username", "full_name")
        indexes = [
            models.Index(fields=["tenant"], name="idx_agent_tenant"),
            models.Index(fields=["division"], name="idx_agent_division"),
            models.Index(fields=["account_type"], name="idx_agent_acct_type"),
            models.Index(fields=["account_role"], name="idx_agent_acct_role"),
            models.Index(fields=["last_modified"], name="idx_agent_last_modified"),
        ]
    def save(self, *args, **kwargs):
        # always use current UTC time in seconds
        self.last_modified = int(time.time())
        # if new object, set date_created too
        if not self.date_created:
            self.date_created = self.last_modified
        super().save(*args, **kwargs)

class Warehouse(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255)
    address_line1 = models.CharField(max_length=60)
    address_line2 = models.CharField(max_length=60, blank=True, null=True)
    city = models.CharField(max_length=30)
    state = models.CharField(max_length=30)
    zipcode = models.CharField(max_length=20)
    country = models.CharField(max_length=50)

    description  = models.CharField(max_length=255, blank=True, null=True)
    description2 = models.CharField(max_length=255, blank=True, null=True)
    description3 = models.CharField(max_length=255, blank=True, null=True)

    last_modified = models.BigIntegerField(editable=False)
    modified_by = models.ForeignKey("Agent", on_delete=models.PROTECT)
    date_created = models.BigIntegerField(editable=False)

    class Meta:
        db_table = "warehouse"
        unique_together = ("name","address_line1","city","state","zipcode","country")
        indexes = [
            models.Index(fields=["name","city"], name="idx_wh_name_city"),
        ]

    def save(self,*a,**k):
        now = int(time.time())
        self.last_modified = now
        if not self.date_created:
            self.date_created = now
        return super().save(*a,**k)


class StockMovement(models.Model):
    """
    دفتر الحركات: الحقيقة المحاسبية الوحيدة للمخزون.
    لا يغيّر Inventory.qty تلقائيًا في هذه المرحلة؛ فقط يسجل حركة.
    """
    # ثوابت أنواع الحركة
    INBOUND_RECEIPT         = "INBOUND_RECEIPT"          # توريد داخل المستودع
    DISPATCH_TO_BRANCH      = "DISPATCH_TO_BRANCH"       # إرسال من المستودع لفرع
    RECEIVE_FROM_WAREHOUSE  = "RECEIVE_FROM_WAREHOUSE"   # استلام الفرع لشحنة المستودع
    RESERVE                 = "RESERVE"                  # حجز أثناء السلة
    UNRESERVE               = "UNRESERVE"                # فك الحجز
    CONSUME_RESERVATION     = "CONSUME_RESERVATION"      # استهلاك الحجز (تأكيد البيع)
    ADJUSTMENT_IN           = "ADJUSTMENT_IN"            # تسوية زيادة
    ADJUSTMENT_OUT          = "ADJUSTMENT_OUT"           # تسوية نقص
    RETURN_TO_WAREHOUSE     = "RETURN_TO_WAREHOUSE"      # مرتجع من فرع للمستودع
    RETURN_TO_SUPPLIER      = "RETURN_TO_SUPPLIER"       # مرتجع للمورّد

    MOVEMENT_TYPES = [
        (INBOUND_RECEIPT,        "Inbound Receipt"),
        (DISPATCH_TO_BRANCH,     "Dispatch to Branch"),
        (RECEIVE_FROM_WAREHOUSE, "Receive from Warehouse"),
        (RESERVE,                "Reserve"),
        (UNRESERVE,              "Unreserve"),
        (CONSUME_RESERVATION,    "Consume Reservation"),
        (ADJUSTMENT_IN,          "Adjustment In"),
        (ADJUSTMENT_OUT,         "Adjustment Out"),
        (RETURN_TO_WAREHOUSE,    "Return to Warehouse"),
        (RETURN_TO_SUPPLIER,     "Return to Supplier"),
    ]

    # حالات الحركة
    PENDING  = "PENDING"
    POSTED   = "POSTED"
    CANCELED = "CANCELED"
    STATUS_CHOICES = [(PENDING, "Pending"), (POSTED, "Posted"), (CANCELED, "Canceled")]

    id = models.AutoField(primary_key=True)
    tenant  = models.ForeignKey("Tenant", db_column="tenant", on_delete=models.CASCADE)
    product = models.ForeignKey("Product", db_column="product", on_delete=models.PROTECT)

    movement_type = models.CharField(max_length=32, choices=MOVEMENT_TYPES)
    status        = models.CharField(max_length=16, choices=STATUS_CHOICES, default=PENDING)

    # من (اختياري)
    from_content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT, related_name="sm_from_ct", null=True, blank=True)
    from_object_id    = models.PositiveIntegerField(null=True, blank=True)
    from_location     = GenericForeignKey("from_content_type", "from_object_id")

    # إلى (اختياري)
    to_content_type = models.ForeignKey(ContentType, on_delete=models.PROTECT, related_name="sm_to_ct", null=True, blank=True)
    to_object_id    = models.PositiveIntegerField(null=True, blank=True)
    to_location     = GenericForeignKey("to_content_type", "to_object_id")

    qty = models.PositiveIntegerField()  # الكمية دائمًا موجبة؛ نوع الحركة يحدد الاتجاه

    # مرجع اختياري لوثيقة عليا (تحويل/إيصال/طلب...)
    ref_type = models.CharField(max_length=32, blank=True, null=True)
    ref_id   = models.CharField(max_length=64, blank=True, null=True)

    # مفتاح إديمبوتنسي لمنع التكرار عند إعادة المحاولة
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    notes = models.TextField(blank=True, null=True)

    # الطوابع والمستخدمين
    created_by    = models.ForeignKey("Agent", db_column="created_by", on_delete=models.PROTECT, related_name="stockmovement_created_by")
    modified_by   = models.ForeignKey("Agent", on_delete=models.PROTECT, related_name="stockmovement_modified_by")
    date_created  = models.BigIntegerField(editable=False)
    last_modified = models.BigIntegerField(editable=False)

    class Meta:
        db_table = "stock_movement"
        indexes = [
            models.Index(fields=["tenant", "product", "date_created"], name="idx_sm_tpp_date"),
            models.Index(fields=["movement_type", "status"], name="idx_sm_type_status"),
            models.Index(fields=["from_content_type", "from_object_id"], name="idx_sm_from"),
            models.Index(fields=["to_content_type", "to_object_id"], name="idx_sm_to"),
        ]

    def clean(self):
        # تحقق عام: لازم يكون في مصدر أو وجهة (واحد على الأقل)
        if not self.from_content_type and not self.to_content_type:
            raise ValidationError("StockMovement requires at least a source or a destination location.")
        if self.qty <= 0:
            raise ValidationError("qty must be > 0")

    def save(self, *args, **kwargs):
        now = int(time.time())
        self.last_modified = now
        if not self.date_created:
            self.date_created = now
        super().save(*args, **kwargs)

class Branch(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255)
    address_line1 = models.CharField(max_length=60)
    address_line2 = models.CharField(max_length=60, blank=True, null=True)
    city = models.CharField(max_length=30)
    state = models.CharField(max_length=30)
    zipcode = models.CharField(max_length=20)
    country = models.CharField(max_length=50)

    description  = models.CharField(max_length=255, blank=True, null=True)
    description2 = models.CharField(max_length=255, blank=True, null=True)
    description3 = models.CharField(max_length=255, blank=True, null=True)

    last_modified = models.BigIntegerField(editable=False)
    modified_by   = models.ForeignKey("Agent", on_delete=models.PROTECT)
    date_created  = models.BigIntegerField(editable=False)

    class Meta:
        db_table = "branch"
        unique_together = ("name", "address_line1", "city", "state", "zipcode", "country")
        indexes = [
            models.Index(fields=["name", "city"], name="idx_branch_name_city"),
        ]

    def save(self, *args, **kwargs):
        now = int(time.time())
        self.last_modified = now
        if not self.date_created:
            self.date_created = now
        return super().save(*args, **kwargs)
class Inventory(models.Model):
    id = models.AutoField(primary_key=True)
    tenant = models.ForeignKey("Tenant", on_delete=models.CASCADE, db_column="tenant")
    product = models.ForeignKey("Product", on_delete=models.PROTECT, db_column="product", null=True, blank=True)

    qty = models.IntegerField(default=0)

    name = models.CharField(max_length=255, default="", blank=True)
    unit = models.IntegerField(default=1)
    status = models.CharField(max_length=255, default="")
    supply_chain = models.CharField(max_length=255, default="")

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    target = GenericForeignKey("content_type", "object_id")

    class Meta:
        db_table = "inventory"
        indexes = [
            models.Index(fields=["tenant"], name="idx_inv_tenant"),
            models.Index(fields=["tenant", "product", "content_type", "object_id"], name="idx_inv_tpc_loc"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "product", "content_type", "object_id"],
                name="uq_inv_tenant_product_location"
            ),
            models.CheckConstraint(check=models.Q(qty__gte=0), name="ck_inv_qty_nonnegative"),
        ]
class Product(models.Model):
    id = models.AutoField(primary_key=True)
    tenant = models.ForeignKey("Tenant", to_field="id", db_column="tenant", on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    sku = models.CharField(max_length=100, unique=True)

    CATEGORY_CHOICES = [
        ("breads","breads"), ("cakes","cakes"), ("donuts","donuts"),
        ("pastries","pastries"), ("sandwich","sandwich"),
    ]
    category = models.CharField(max_length=100, choices=CATEGORY_CHOICES)

    price = models.DecimalField(max_digits=10, decimal_places=2)

    size = models.IntegerField(default=0)
    SIZE_UNITS = [("piece","piece"),("g","g"),("kg","kg"),("ml","ml"),("l","l")]
    size_unit = models.CharField(max_length=16, choices=SIZE_UNITS, default="piece")

    image = models.URLField(blank=True, null=True)
    status = models.BooleanField(default=True)

    last_modified = models.BigIntegerField(editable=False)
    modified_by = models.ForeignKey("Agent", on_delete=models.PROTECT, related_name="product_modified_by")
    date_created = models.BigIntegerField(editable=False,blank=True)
    created_by = models.ForeignKey("Agent", db_column="created_by", on_delete=models.PROTECT, related_name="product_created_by" , blank=True, null=True)

    class Meta:
        db_table = "product"
        indexes = [
            models.Index(fields=["tenant"],   name="idx_product_tenant"),
            models.Index(fields=["category"], name="idx_pp_category"),
            models.Index(fields=["size"],     name="idx_pp_size"),
            models.Index(fields=["size_unit"],name="idx_pp_size_unit"),
        ]

    def save(self,*a,**k):
        now = int(time.time())
        self.last_modified = now
        if not self.date_created:
            self.date_created = now
        return super().save(*a,**k)
class SupplyChain(models.Model):
    id = models.AutoField(primary_key=True)
    tenant = models.ForeignKey("Tenant", to_field="id", db_column="tenant",
                               on_delete=models.CASCADE, null=True, blank=True)
    name = models.CharField(max_length=255, unique=True)
    date_created  = models.BigIntegerField(editable=False, null=True, blank=True)
    last_modified = models.BigIntegerField(editable=False, null=True, blank=True)
    modified_by   = models.ForeignKey("Agent", on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        db_table = "supply_chain"
        indexes = [models.Index(fields=["name"], name="idx_supplychain_name")]

    def save(self, *a, **k):
        now = int(time.time())
        self.last_modified = now
        if not self.date_created:
            self.date_created = now
        return super().save(*a, **k)

class Supplier(models.Model):
    id   = models.AutoField(primary_key=True)
    tenant = models.ForeignKey("Tenant", to_field="id", db_column="tenant",
                               on_delete=models.CASCADE, null=True, blank=True)
    name = models.CharField(max_length=255, unique=True)
    contact_email = models.CharField(max_length=255, blank=True, null=True)
    phone_number  = models.CharField(max_length=50,  blank=True, null=True)
    address       = models.CharField(max_length=255, blank=True, null=True)

    # 👇 Many-to-Many عبر موديل وسيط
    supply_chains = models.ManyToManyField(
        SupplyChain, through="SupplierSupplyChain", related_name="suppliers"
    )

    date_created  = models.BigIntegerField(editable=False, null=True, blank=True)
    last_modified = models.BigIntegerField(editable=False, null=True, blank=True)
    modified_by   = models.ForeignKey("Agent", on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        db_table = "supplier"
        indexes = [models.Index(fields=["name"], name="idx_supplier_name")]

    def save(self, *a, **k):
        now = int(time.time())
        self.last_modified = now
        if not self.date_created:
            self.date_created = now
        return super().save(*a, **k)

class SupplierSupplyChain(models.Model):
    """العلاقة الوسيطة مع بيانات إضافية عن الربط"""
    id = models.AutoField(primary_key=True)
    tenant = models.ForeignKey("Tenant", to_field="id", db_column="tenant",
                               on_delete=models.CASCADE, null=True, blank=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE)
    supply_chain = models.ForeignKey(SupplyChain, on_delete=models.CASCADE)

    # بيانات تشغيلية مفيدة
    lead_time_days = models.IntegerField(default=0)       # مدة التوريد
    contract_no    = models.CharField(max_length=100, blank=True, null=True)
    start_date     = models.BigIntegerField(null=True, blank=True)
    end_date       = models.BigIntegerField(null=True, blank=True)
    priority       = models.IntegerField(default=0)       # 0 أعلى أولوية لو تحب
    status         = models.CharField(max_length=30, default="Active")  # Active/Paused/Ended

    date_created   = models.BigIntegerField(editable=False, null=True, blank=True)
    last_modified  = models.BigIntegerField(editable=False, null=True, blank=True)
    modified_by    = models.ForeignKey("Agent", on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        db_table = "supplier_supply_chain"
        unique_together = ("supplier", "supply_chain")  # تمنع التكرار
        indexes = [
            models.Index(fields=["supplier"], name="idx_ssc_supplier"),
            models.Index(fields=["supply_chain"], name="idx_ssc_chain"),
            models.Index(fields=["status"], name="idx_ssc_status"),
        ]

    def save(self, *a, **k):
        now = int(time.time())
        self.last_modified = now
        if not self.date_created:
            self.date_created = now
        return super().save(*a, **k)


class Promotion(models.Model):
    id = models.AutoField(primary_key=True)
    tenant = models.ForeignKey("Tenant", to_field="id", db_column="tenant", on_delete=models.CASCADE)
    product = models.ForeignKey("Product", db_column="product", to_field="id", on_delete=models.PROTECT)

    description  = models.CharField(max_length=255, blank=True, null=True)
    description2 = models.CharField(max_length=255, blank=True, null=True)
    description3 = models.CharField(max_length=255, blank=True, null=True)

    # نوع الخصم: نسبة مئوية أم مبلغ ثابت
    DISCOUNT_TYPE = [("percent","percent"), ("amount","amount")]
    discount_type  = models.CharField(max_length=10, choices=DISCOUNT_TYPE, default="percent")
    discount_value = models.DecimalField(max_digits=10, decimal_places=2)  # لو percent: 0-100

    # نطاق التطبيق: على كل وحدة أو على إجمالي الطلب
    DISCOUNT_SCOPE = [("unit","per unit"), ("total","order total")]
    discount_scope = models.CharField(max_length=10, choices=DISCOUNT_SCOPE, default="unit")

    # اختياري: كمية مستهدفة (مثلاً خصم عند شراء N)
    discount_qty = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    start_date = models.BigIntegerField(null=True, blank=True)
    end_date   = models.BigIntegerField(null=True, blank=True)

    last_modified = models.BigIntegerField(editable=False)
    modified_by   = models.ForeignKey("Agent", on_delete=models.PROTECT, related_name="promotion_modified_by")
    date_created  = models.BigIntegerField(editable=False)
    created_by    = models.ForeignKey("Agent", db_column="created_by", on_delete=models.PROTECT, related_name="promotion_created_by")

    frequency = models.CharField(max_length=30, blank=True)

    class Meta:
        db_table = "promotion"
        indexes = [
            models.Index(fields=["tenant"], name="idx_promo_tenant"),
            models.Index(fields=["product"], name="idx_promo_product"),
            models.Index(fields=["start_date"], name="idx_promo_start"),
            models.Index(fields=["end_date"], name="idx_promo_end"),
        ]

    def save(self,*a,**k):
        import time
        now = int(time.time())
        self.last_modified = now
        if not self.date_created:
            self.date_created = now
        return super().save(*a,**k)

class PromotionCampaign(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=150)
    tenant = models.ForeignKey("Tenant", to_field="id", db_column="tenant", on_delete=models.CASCADE)

    promotion = models.ForeignKey("Promotion", db_column="promotion", to_field="id", on_delete=models.PROTECT)
    branch = models.ForeignKey("Branch", to_field="id", db_column="branch", on_delete=models.PROTECT)

    start_date = models.BigIntegerField()
    end_date   = models.BigIntegerField()

    description  = models.CharField(max_length=255, blank=True, null=True)
    description2 = models.CharField(max_length=255, blank=True, null=True)
    description3 = models.CharField(max_length=255, blank=True, null=True)

    last_modified = models.BigIntegerField(editable=False)
    modified_by   = models.ForeignKey("Agent", on_delete=models.PROTECT)
    date_created  = models.BigIntegerField(editable=False)

    class Meta:
        db_table = "campaign"
        unique_together = ("name", "promotion", "branch", "start_date", "end_date")
        indexes = [
            models.Index(fields=["tenant"],   name="idx_campaign_tenant"),
            models.Index(fields=["name"],     name="idx_campaign_name"),
            models.Index(fields=["promotion"],name="idx_campaign_promo"),
            models.Index(fields=["branch"],   name="idx_campaign_branch"),
            models.Index(fields=["start_date"],name="idx_campaign_start"),
            models.Index(fields=["end_date"], name="idx_campaign_end"),
        ]

    def save(self,*a,**k):
        import time
        now = int(time.time())
        self.last_modified = now
        if not self.date_created:
            self.date_created = now
        return super().save(*a,**k)

class LoyaltyProgram(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=255)
    tenant = models.ForeignKey("Tenant", db_column="tenant", on_delete=models.CASCADE)

    description  = models.CharField(max_length=255, blank=True, null=True)
    description2 = models.CharField(max_length=255, blank=True, null=True)
    description3 = models.CharField(max_length=255, blank=True, null=True)

    last_modified = models.BigIntegerField(editable=False)
    modified_by   = models.ForeignKey("Agent", on_delete=models.PROTECT)
    date_created  = models.BigIntegerField(editable=False)
    frequency     = models.CharField(max_length=30)

    class Meta:
        db_table = "loyalty_program"

class LoyaltyBenefits(models.Model):
    id = models.AutoField(primary_key=True)
    tenant = models.ForeignKey("Tenant", db_column="tenant", on_delete=models.CASCADE)
    product = models.ForeignKey("Product", db_column="product", on_delete=models.PROTECT)
    loyalty_program = models.ForeignKey("LoyaltyProgram", db_column="loyalty_program", on_delete=models.CASCADE)

    start_period = models.BigIntegerField()
    end_period   = models.BigIntegerField()

    PERIOD_TYPES = [("days","days"),("weeks","weeks"),("months","months")]
    period_type = models.CharField(max_length=32, choices=PERIOD_TYPES, default="days")

    class Meta:
        db_table = "loyalty_benefits"
        indexes = [
            models.Index(fields=["tenant"], name="idx_lb_tenant"),
            models.Index(fields=["loyalty_program"], name="idx_lb_program"),
            models.Index(fields=["product"], name="idx_lb_product"),
        ]



class Sales(models.Model):
    id = models.AutoField(primary_key=True)

    tenant  = models.ForeignKey("Tenant", db_column="tenant", on_delete=models.CASCADE)

    # مكان البيع (POS)
    branch = models.ForeignKey("Branch", db_column="branch", on_delete=models.PROTECT)

    # مصدر المخزون (اختياري)
    warehouse = models.ForeignKey(
        "Warehouse", db_column="warehouse", on_delete=models.SET_NULL,
        null=True, blank=True
    )

    # المنتج المباع
    product = models.ForeignKey("Product", db_column="product", on_delete=models.PROTECT)

    # ارتباطات اختيارية
    promotion_campaign = models.ForeignKey(
        "PromotionCampaign", db_column="campaign", on_delete=models.SET_NULL,
        null=True, blank=True
    )
    loyalty_benefits = models.ForeignKey(
        "LoyaltyBenefits", db_column="benefits", on_delete=models.SET_NULL,
        null=True, blank=True
    )

    # لقطات وقت البيع (لا تعتمد على جداول تتغير لاحقًا)
    unit_sold = models.IntegerField(default=1)
    unit_price_snapshot = models.DecimalField(max_digits=12, decimal_places=2)
    discount_value_applied = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_value_applied      = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    line_total             = models.DecimalField(max_digits=14, decimal_places=2)

    currency  = models.CharField(max_length=10, default="USD")
    order_id  = models.CharField(max_length=64, blank=True, null=True)   # رقم طلب/فاتورة
    receipt_no= models.CharField(max_length=64, blank=True, null=True)

    # معلومات منزوعة (denormalized) مفيدة للتقارير السريعة
    product_sku_snapshot   = models.CharField(max_length=100)
    product_name_snapshot  = models.CharField(max_length=255)
    branch_name_snapshot   = models.CharField(max_length=255)

    # طوابع زمنية ومن أنشأ/عدل
    date_created  = models.BigIntegerField(editable=False)
    last_modified = models.BigIntegerField(editable=False)
    created_by    = models.ForeignKey("Agent", db_column="created_by", on_delete=models.PROTECT,
                                      related_name="sale_created_by")
    modified_by   = models.ForeignKey("Agent", on_delete=models.PROTECT, related_name="sale_modified_by")

    class Meta:
        db_table = "sales"
        indexes = [
            models.Index(fields=["tenant"],       name="idx_sales_tenant"),
            models.Index(fields=["branch"],       name="idx_sales_branch"),
            models.Index(fields=["product"],      name="idx_sales_product"),
            models.Index(fields=["date_created"], name="idx_sales_date"),
            models.Index(fields=["order_id"],     name="idx_sales_order"),
            models.Index(fields=["receipt_no"],   name="idx_sales_receipt"),
        ]

    def clean(self):
        if self.unit_sold <= 0:
            raise ValidationError("unit_sold must be > 0")
        # تحقق اختياري لو تحب تضمن صحة الإجمالي
        # expected = self.unit_price_snapshot * self.unit_sold - self.discount_value_applied + self.tax_value_applied
        # if self.line_total != expected:
        #     raise ValidationError("line_total mismatch")

    def save(self, *args, **kwargs):
        now = int(time.time())
        self.last_modified = now
        if not self.date_created:
            self.date_created = now
        return super().save(*args, **kwargs)


class Invoice(models.Model):
    id = models.AutoField(primary_key=True)
    tenant  = models.ForeignKey("Tenant", on_delete=models.CASCADE, db_column="tenant")
    branch  = models.ForeignKey("Branch", on_delete=models.PROTECT, db_column="branch")

    # رقم متسلسل لكل فرع (سهل البحث والطباعة)
    invoice_no = models.CharField(max_length=32, unique=True)
    order_id   = models.CharField(max_length=64, db_index=True)  # يربط طلب POS

    # عميل (اختياري)
    customer_name  = models.CharField(max_length=255, blank=True, null=True)
    customer_phone = models.CharField(max_length=50, blank=True, null=True)
    customer_taxno = models.CharField(max_length=50, blank=True, null=True)

    currency = models.CharField(max_length=10, default="USD")
    payment_method = models.CharField(max_length=20, default="cash")  # cash/card/…
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax      = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total    = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax_rate = models.DecimalField(max_digits=6, decimal_places=4, default=0)

    date_created  = models.BigIntegerField(editable=False)
    last_modified = models.BigIntegerField(editable=False)
    created_by    = models.ForeignKey("Agent", on_delete=models.PROTECT, related_name="invoice_created_by")
    modified_by   = models.ForeignKey("Agent", on_delete=models.PROTECT, related_name="invoice_modified_by")

    class Meta:
        db_table = "invoice"
        indexes = [models.Index(fields=["tenant","branch","order_id"], name="idx_inv_tb_order")]

    def save(self,*a,**k):
        now = int(time.time())
        self.last_modified = now
        if not self.date_created:
            self.date_created = now
        return super().save(*a,**k)

class InvoiceLine(models.Model):
    id = models.AutoField(primary_key=True)
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey("Product", on_delete=models.PROTECT)

    name      = models.CharField(max_length=255)    # snapshot
    sku       = models.CharField(max_length=100)
    qty       = models.IntegerField()
    unit_price= models.DecimalField(max_digits=12, decimal_places=2)
    tax       = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    line_total= models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        db_table = "invoice_line"

class StockTransfer(models.Model):
    """
    تحويل من مستودع → فرع (عملية مركّبة: dispatch ثم receive)
    """
    STATUS_CHOICES = (
        ("POSTED", "Posted"),
    )

    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey("products.Tenant", on_delete=models.CASCADE)
    product = models.ForeignKey("products.Product", on_delete=models.CASCADE)
    warehouse = models.ForeignKey("products.Warehouse", on_delete=models.CASCADE)
    branch = models.ForeignKey("products.Branch", on_delete=models.CASCADE)
    qty = models.IntegerField()
    transfer_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_by = models.ForeignKey("products.Agent", null=True, blank=True, on_delete=models.SET_NULL)
    date_created = models.IntegerField(default=0)  # unix seconds
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="POSTED")

    # اختياري: ربط بحركات المخزون (لو حبيت تتبعها)
    dispatch_movement_id = models.IntegerField(null=True, blank=True)
    receive_movement_id = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = "stock_transfer"
        indexes = [
            models.Index(fields=["tenant", "date_created"]),
            models.Index(fields=["product", "branch"]),
        ]

    def __str__(self):
        return f"Transfer {self.transfer_id} {self.qty} of {self.product_id} → B{self.branch_id}"
