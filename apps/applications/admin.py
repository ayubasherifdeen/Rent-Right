from django.contrib import admin
from .models import Application


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display  = ('__str__', 'status', 'move_in_date', 'created_at')
    list_filter   = ('status',)
    search_fields = ('tenant__email', 'tenant__first_name', 'property__title')
    readonly_fields = ('id', 'created_at', 'updated_at')
    ordering      = ('-created_at',)
