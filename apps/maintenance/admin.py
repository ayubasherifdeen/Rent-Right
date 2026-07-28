from django.contrib import admin

from .models import MaintenanceRequest, MaintenanceRequestMedia, MaintenanceRequestMedia, MaintenanceUpdate


class MaintenanceUpdateInline(admin.TabularInline):
    model = MaintenanceUpdate
    extra = 0
    readonly_fields = ["actor", "old_status", "new_status", "note", "created_at"]
    can_delete = False


class MaintenanceRequestMediaInline(admin.TabularInline):
    model = MaintenanceRequestMedia
    extra = 0
    readonly_fields = ["uploaded_by", "file", "media_type", "stage", "created_at"]
    can_delete = False


@admin.register(MaintenanceRequest)
class MaintenanceRequestAdmin(admin.ModelAdmin):
    list_display = ["id", "title", "category", "status", "tenancy", "reported_by", "created_at"]
    list_filter = ["status", "category"]
    search_fields = ["title", "description"]
    inlines = [MaintenanceUpdateInline, MaintenanceRequestMediaInline]
