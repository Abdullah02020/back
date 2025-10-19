from django.contrib import admin
from .models import Product

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "sku", "category", "price",  "active")
    search_fields = ("name", "sku", "category")

    def active(self, obj):
        return obj.status   # نربط active بالـ status في الموديل
    active.boolean = True   # يظهر كـ ✅/❌ في لوحة الأدمن
