# backend/products/serializers.py

from decimal import Decimal
from rest_framework import serializers
from .models import Product


# ============ Products ============
class ProductSerializer(serializers.ModelSerializer):
    modified_by_name = serializers.CharField(source="modified_by.full_name", read_only=True)
    created_by_name  = serializers.CharField(source="created_by.full_name",  read_only=True)

    class Meta:
        model = Product
        fields = [
            "id", "tenant", "name", "sku", "category",
            "price", "size", "size_unit",
            "image", "status",
            "last_modified", "modified_by", "modified_by_name",
            "date_created", "created_by", "created_by_name",
        ]
        read_only_fields = ["last_modified", "date_created", "created_by", "modified_by"]

    def create(self, validated_data):
        return super().create(validated_data)

    def update(self, instance, validated_data):
        return super().update(instance, validated_data)


# ============ Orders (Create) ============
# طلب الإدخال: أسطر الطلب
class OrderLineInSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(min_value=1)
    qty        = serializers.IntegerField(min_value=1)

# جسم الطلب عند الإنشاء
class CreateOrderSerializer(serializers.Serializer):
    lines = OrderLineInSerializer(many=True)
    payment_method = serializers.ChoiceField(choices=["cash", "card", "other"], default="cash")
    # نقبل 0.10 أو 10.00 (سيتم التطبيع في الـ view)
    tax_rate = serializers.DecimalField(max_digits=5, decimal_places=2, required=False)

# سطر واحد في استجابة إنشاء الطلب
class OrderLineOutSerializer(serializers.Serializer):
    product_id   = serializers.IntegerField()
    sku          = serializers.CharField()
    product_name = serializers.CharField()
    qty          = serializers.IntegerField()
    unit_price   = serializers.CharField()   # كنص للحفاظ على الدقة (Decimal)
    line_total   = serializers.CharField()
    new_stock    = serializers.IntegerField()

# الاستجابة الكاملة لإنشاء الطلب
class OrderCreatedSerializer(serializers.Serializer):
    order_id   = serializers.CharField()
    subtotal   = serializers.CharField()
    tax        = serializers.CharField()
    total      = serializers.CharField()
    currency   = serializers.CharField()
    created_at = serializers.IntegerField()
    lines      = OrderLineOutSerializer(many=True)



class StockReceiveSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    warehouse_id = serializers.IntegerField()
    qty = serializers.IntegerField(min_value=1)
    notes = serializers.CharField(required=False, allow_blank=True)
    idempotency_key = serializers.UUIDField(required=False)

class StockDispatchSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    warehouse_id = serializers.IntegerField()
    branch_id = serializers.IntegerField()
    qty = serializers.IntegerField(min_value=1)
    notes = serializers.CharField(required=False, allow_blank=True)
    idempotency_key = serializers.UUIDField(required=False)

class BranchReceiveSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    branch_id = serializers.IntegerField()
    qty = serializers.IntegerField(min_value=1)
    notes = serializers.CharField(required=False, allow_blank=True)
    idempotency_key = serializers.UUIDField(required=False)
