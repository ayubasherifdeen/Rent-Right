from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from .models import Amenity, Property, PropertyPhoto


@admin.register(Amenity)
class AmenityAdmin(admin.ModelAdmin):
    list_display  = ('name', 'icon', 'display_order')
    ordering      = ('display_order', 'name')
    search_fields = ('name',)


class PropertyPhotoInline(admin.TabularInline):
    """
    TabularInline shows photos as a compact table (vs StackedInline which shows each
    photo on its own row of fields). Better for multiple images.
    """
    model       = PropertyPhoto
    extra       = 1         # show 1 empty form by default
    fields      = ('image', 'caption', 'is_primary', 'display_order')
    readonly_fields = ('thumbnail_preview',)

    def thumbnail_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="height:60px;border-radius:4px;">', obj.image.url)
        return "—"
    thumbnail_preview.short_description = 'Preview'


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display  = (
        'title', 'property_type', 'city', 'monthly_rent',
        'advance_months', 'status', 'act_220_badge', 'created_at'
    )
    list_filter   = ('status', 'property_type', 'city', 'has_instalment_plan')
    search_fields = ('title', 'address', 'neighbourhood')
    readonly_fields = ('created_at', 'updated_at', 'views_count', 'advance_amount_display')
    filter_horizontal = ('amenities',)  # dual-panel widget for ManyToMany
    inlines       = [PropertyPhotoInline]

    fieldsets = (
        ('Core', {
            'fields': ('landlord', 'title', 'description', 'property_type', 'status')
        }),
        ('Size & Furnishing', {
            'fields': ('bedrooms', 'bathrooms', 'furnishing_status')
        }),
        ('Location', {
            'fields': ('address', 'neighbourhood', 'city', 'region', 'latitude', 'longitude')
        }),
        ('Lease Term', {
            'fields': ('lease_term_months',),
            'description': 'Total tenancy duration. Drives rent card, addendum, and tenancy end date.'
        }),
        ('Financials — Act 220', {
            'fields': (
                'monthly_rent', 'payment_cycle', 'advance_months',
                'advance_amount_display', 'security_deposit', 'has_instalment_plan'
            ),
            'description': (
                '⚠️ Section 25(5) of Act 220 caps advance rent at 6 months. '
                'The system enforces this — values above 6 will be rejected.'
            )
        }),
        ('Amenities', {
            'fields': ('amenities',)
        }),
        ('Metadata', {
            'fields': ('available_from', 'created_at', 'updated_at', 'views_count', 'video_url'),
            'classes': ('collapse',)
        }),
    )

    def act_220_badge(self, obj):
        if obj.act_220_compliant:
            return mark_safe(
                '<span style="color:#1C3829;font-weight:600;">✅ Compliant</span>'
            )
        return format_html('<span style="color:#C4622D;font-weight:600;">❌ Violation</span>')
    act_220_badge.short_description = 'Act 220'

    def advance_amount_display(self, obj):
        if obj.monthly_rent and obj.advance_months:
            return f"GHC {obj.advance_amount:,.2f}"
        return "—"
    advance_amount_display.short_description = 'Total advance payment'
