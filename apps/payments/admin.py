from django.contrib import admin

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tenancy",
        "payment_type",
        "status",
        "amount",
        "instalment_due_date",
        "reference",
        "created_at",
    )
    list_filter = ("payment_type", "status")
    search_fields = ("reference", "paystack_transaction_id", "tenancy__id", "paid_by__email")
    readonly_fields = ("gateway_response", "paystack_transaction_id", "created_at", "updated_at")
