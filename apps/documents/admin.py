from django.contrib import admin

from .models import Document


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "document_type", "content_type", "object_id", "generated_at", "generated_by")
    list_filter = ("document_type", "content_type")
    readonly_fields = ("id", "generated_at", "content_type", "object_id", "file")
    search_fields = ("object_id",)
    date_hierarchy = "generated_at"
