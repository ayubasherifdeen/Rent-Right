from django.contrib import admin

from apps.tenancies.models import Agreement, Tenancy


@admin.register(Tenancy)
class TenancyAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "tenant",
        "landlord",
        "rental_property",
        "status",
        "monthly_rent",
        "advance_months",
        "start_date",
        "end_date",
        "created_at",
    ]
    list_filter = ["status", "created_at"]
    search_fields = [
        "tenant__email",
        "landlord__email",
        "rental_property__title",
    ]
    readonly_fields = [
        "id",
        "advance_amount",
        "end_date",
        "created_at",
        "updated_at",
    ]
    raw_id_fields = ["application", "rental_property", "landlord", "tenant"]


@admin.register(Agreement)
class AgreementAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "tenancy",
        "status",
        "landlord_confirmed_at",
        "tenant_confirmed_at",
        "fully_executed_at",
        "created_at",
    ]
    list_filter = ["status", "created_at"]
    search_fields = [
        "tenancy__tenant__email",
        "tenancy__landlord__email",
    ]
    readonly_fields = [
        "id",
        "landlord_confirmed_at",
        "landlord_otp_ref",
        "tenant_confirmed_at",
        "tenant_otp_ref",
        "fully_executed_at",
        "created_at",
        "updated_at",
    ]
    raw_id_fields = ["tenancy"]
