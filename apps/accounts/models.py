import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


# Role constants

class Role(models.TextChoices):
    TENANT          = 'tenant',           _('Tenant')
    LANDLORD        = 'landlord',         _('Landlord')
    PROPERTY_MANAGER = 'property_manager', _('Property Manager')
    ADMIN           = 'admin',            _('System Admin')


# ─── Organisation ─────────────────────────────────────────────────────────────
# Optional FK from UserProfile — not used in MVP, but avoids a painful
# migration if/when we add multi-tenant support for property management firms.

class Organisation(models.Model):
    id                  = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name                = models.CharField(max_length=255)
    registration_number = models.CharField(max_length=100, blank=True)
    address             = models.TextField(blank=True)
    created_at          = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Organisation'

    def __str__(self):
        return self.name


# Custom User with AbstractUser, users are identified by email

class User(AbstractUser):
    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email        = models.EmailField(_('email address'), unique=True)
    phone_number = models.CharField(max_length=20, blank=True)
    is_verified  = models.BooleanField(default=False)  # phone OTP confirmed

    USERNAME_FIELD  = 'email'
    REQUIRED_FIELDS = ['username', 'first_name', 'last_name']

    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'

    def __str__(self):
        return self.email

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip() or self.email

    @property
    def role(self):
        """Convenience shortcut — avoids .userprofile.role in templates."""
        try:
            return self.userprofile.role
        except UserProfile.DoesNotExist:
            return None

    def is_landlord(self):
        return self.role == Role.LANDLORD

    def is_tenant(self):
        return self.role == Role.TENANT

    def is_property_manager(self):
        return self.role == Role.PROPERTY_MANAGER

    def is_system_admin(self):
        return self.role == Role.ADMIN or self.is_staff


# UserProfile
# Keeps role-specific fields separate from auth concerns.
# Created automatically via signal on User creation.

class UserProfile(models.Model):
    user         = models.OneToOneField(User, on_delete=models.CASCADE, related_name='userprofile')
    role         = models.CharField(max_length=20, choices=Role.choices, default=Role.TENANT)
    organisation = models.ForeignKey(
        Organisation,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='members',
        help_text='For property managers belonging to a management firm (future use).',
    )
    national_id      = models.CharField(max_length=50, blank=True)
    profile_photo    = models.ImageField(upload_to='profiles/', blank=True, null=True)
    bio              = models.TextField(blank=True)
    is_id_verified   = models.BooleanField(default=False)
    created_at       = models.DateTimeField(auto_now_add=True)
    updated_at       = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'User Profile'

    def __str__(self):
        return f"{self.user.full_name} ({self.get_role_display()})"


# OTP 
# Used for:
#   1. Phone number verification on registration
#   2. Bilateral tenancy confirmation (both parties OTP before docs generated)
#   3. Password reset via SMS

OTP_PURPOSE_CHOICES = [
    ('phone_verify', 'Phone Verification'),
    ('tenancy_confirm', 'Tenancy Confirmation'),
    ('password_reset', 'Password Reset'),
]

class OTP(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name='otps')
    code       = models.CharField(max_length=6)
    purpose    = models.CharField(max_length=20, choices=OTP_PURPOSE_CHOICES)
    is_used    = models.BooleanField(default=False)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'OTP'

    def __str__(self):
        return f"OTP({self.purpose}) for {self.user.email}"

    @property
    def is_valid(self):
        return not self.is_used and timezone.now() < self.expires_at

    def consume(self):
        """Mark OTP as used. Call this inside an atomic block."""
        self.is_used = True
        self.save(update_fields=['is_used'])

