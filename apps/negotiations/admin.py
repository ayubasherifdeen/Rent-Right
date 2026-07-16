from django.contrib import admin

from apps.negotiations.models import Proposal


@admin.register(Proposal)
class ProposalAdmin(admin.ModelAdmin):
    list_display = ("id", "tenancy", "proposed_by", "status", "advance_months", "created_at")
    list_filter = ("status",)
    readonly_fields = ("id", "created_at")
