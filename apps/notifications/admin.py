from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ["id", "user", "purpose", "status", "created_at"]
    list_filter = ["status", "purpose"]
    search_fields = ["message", "error"]
    readonly_fields = [
        "user", "purpose", "message", "status",
        "provider_message_id", "error", "created_at",
    ]

    def has_add_permission(self, request):
        return False  # log rows are only ever created by notify_user()
