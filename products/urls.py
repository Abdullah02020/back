# backend/products/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ProductViewSet, create_order, sales_kpi_summary, revenue_over_time, \
    daily_revenue_chart, top_products_and_categories, available_products_summary, \
    InvoiceView, OrdersView, inventory_receive, StockReceiveWarehouseView, \
    BranchReceiveFromWarehouseView, StockDispatchToBranchView, warehouse_products_summary, \
    stock_receive_from_warehouse, stock_movements, stock_dispatch_to_branch, \
    stock_receive_warehouse, transfer_receipt_html, transfers  # OrdersView غير ضروري الآن

router = DefaultRouter()
router.register(r'products', ProductViewSet, basename='product')  # /api/products/

urlpatterns = [
    path('', include(router.urls)),
    path('orders/', create_order, name='order-create'),  # /api/orders/
    path('orders/', OrdersView.as_view(), name='orders'),  # ✅ استخدم الكلاس

    path("sales-kpi-summary/", sales_kpi_summary, name="sales-kpi-summary"),
    path("revenue-over-time/", revenue_over_time, name="revenue-over-time"),
    path("revenue-chart/", daily_revenue_chart),
    path("top-products-categories/", top_products_and_categories),
    path("available-products-summary/", available_products_summary),
    path("invoices/", InvoiceView.as_view()),  # POST إنشاء
    path("invoices/<str:invoice_no>/html", InvoiceView.as_view()),  # GET طباعة HTML
    path("inventory/receive/", inventory_receive),
    path('stock/warehouse/receive/', StockReceiveWarehouseView.as_view(), name='stock_wh_receive'),
    path('stock/warehouse/dispatch/', StockDispatchToBranchView.as_view(), name='stock_wh_dispatch'),
    path('stock/branch/receive/', BranchReceiveFromWarehouseView.as_view(), name='stock_br_receive'),
    path("warehouse-products-summary/", warehouse_products_summary),
    path("receive-warehouse/", stock_receive_warehouse),
    path("dispatch-to-branch/", stock_dispatch_to_branch),
    path("receive-from-warehouse/", stock_receive_from_warehouse),
    path("movements/", stock_movements),
    path("transfers/", transfers, name="transfers"),
    path("transfers/<uuid:transfer_id>/html", transfer_receipt_html, name="transfer_receipt_html"),

]
