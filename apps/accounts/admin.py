from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

from .models import OTP, Organisation, User, UserProfile


@admin.register(Organisation)
class OrganisationAdmin(admin.ModelAdmin):
    list_display  = ['name', 'registration_number', 'created_at']
    search_fields = ['name', 'registration_number']


class UserProfileInline(admin.StackedInline):
    model      = UserProfile
    can_delete = False
    extra      = 0
    verbose_name_plural = 'Profile'
    fields = ['role', 'organisation', 'national_id', 'profile_photo', 'is_id_verified', 'bio']


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    inlines         = [UserProfileInline]
    list_display    = ['email', 'full_name', 'role', 'is_verified', 'is_active', 'date_joined']
    list_filter     = ['is_active', 'is_verified', 'userprofile__role']
    search_fields   = ['email', 'first_name', 'last_name', 'phone_number']
    ordering        = ['-date_joined']
    readonly_fields = ['id', 'date_joined', 'last_login']
    fieldsets = (
        (None,               {'fields': ('email', 'password')}),
        (_('Personal info'), {'fields': ('first_name', 'last_name', 'phone_number', 'is_verified')}),
        (_('Permissions'),   {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        (_('Important dates'),{'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'username', 'first_name', 'last_name', 'phone_number', 'password1', 'password2'),
        }),
    )

    @admin.display(description='Role')
    def role(self, obj):
        return obj.role or '—'


@admin.register(OTP)
class OTPAdmin(admin.ModelAdmin):
    list_display  = ['user', 'purpose', 'is_used', 'is_valid', 'expires_at', 'created_at']
    list_filter   = ['purpose', 'is_used']
    search_fields = ['user__email']
    readonly_fields = ['id', 'created_at']

    @admin.display(boolean=True)
    def is_valid(self, obj):
        return obj.is_valid

