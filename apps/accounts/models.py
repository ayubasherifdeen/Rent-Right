import uuid
from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.conf import settings


# Roles
class Role(models.TextChoices):
    TENANT          = 'tenant',           _('Tenant')
    LANDLORD        = 'landlord',         _('Landlord')
    PROPERTY_MANAGER = 'property_manager', _('Property Manager')
    ADMIN           = 'admin',            _('System Admin')


# ─── Organisation 
# Optional FK from UserProfile — not used in MVP, but avoids a painful
# migration if/when multi-tenant support for property management firms is added

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


class CustomUserManager(UserManager):
    def create_user(self, username=None, email=None, password=None, **extra_fields):
        if not email:
            raise ValueError("The Email field must be set")

        if not username:
            username = email.split("@", 1)[0]

        base_username = username
        suffix = 1
        while self.model.objects.filter(username=base_username).exists():
            base_username = f"{username}{suffix}"
            suffix += 1

        return super().create_user(username=base_username, email=email, password=password, **extra_fields)

    def create_superuser(self, username=None, email=None, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(username=username, email=email, password=password, **extra_fields)


# Custom User with AbstractUser, users are identified by email

class User(AbstractUser):
    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email        = models.EmailField(_('email address'), unique=True)
    phone_number = models.CharField(max_length=20, blank=True)
    is_verified  = models.BooleanField(default=False)  # phone OTP confirmed

    USERNAME_FIELD  = 'email'
    REQUIRED_FIELDS = ['first_name', 'last_name']

    objects = CustomUserManager()

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


class ManagedProperty(models.Model):
    """
    Relationship between a landlord and a property_manager, mediated by
    a listings.Property. Lives in `accounts` rather than `listings`
    because it's fundamentally about the two Users' relationship, and
    `accounts` already owns role logic — keeps `listings` from having
    to import an `accounts` concept.
    """
 
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
 
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACTIVE = "active", "Active"
        REVOKED = "revoked", "Revoked"
 
    property = models.ForeignKey(
        "listings.Property", on_delete=models.CASCADE,
        related_name="manager_links",
    )
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="managed_properties",
        limit_choices_to={"userprofile__role": "property_manager"},
    )
    # Denormalized off property.landlord on purpose: if a property's
    # landlord FK is ever reassigned, old links should keep showing who
    # *originally* delegated, not silently follow the new owner.
    landlord = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="delegated_properties",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING,
    )
    invited_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
 
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["property", "manager"],
                condition=models.Q(status__in=["pending", "active"]),
                name="one_active_link_per_property_manager",
            )
        ]
 
    def __str__(self):
        return f"{self.manager} -> {self.property} ({self.status})"

