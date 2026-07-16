import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator
from django.db import models


class TenancyStatus(models.TextChoices):
    PENDING_NEGOTIATION = "pending_negotiation", "Pending Negotiation"  
    PENDING_AGREEMENT   = "pending_agreement",   "Pending Agreement"    
    PENDING_PAYMENT     = "pending_payment",     "Pending Payment"
    ACTIVE              = "active",              "Active"
    EXPIRING            = "expiring",            "Expiring"
    ENDED               = "ended",               "Ended"


class Tenancy(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    application = models.OneToOneField(
        "applications.Application",
        on_delete=models.PROTECT,
        related_name="tenancy",
    )
    rental_property = models.ForeignKey(
        "listings.Property",
        on_delete=models.PROTECT,
        related_name="tenancies",
    )
    landlord = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="tenancies_as_landlord",
    )
    tenant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="tenancies_as_tenant",
    )

    # machine: PENDING_NEGOTIATION -> PENDING_AGREEMENT -> PENDING_PAYMENT
    # -> ACTIVE -> EXPIRING -> ENDED.
    status = models.CharField(
        max_length=20,
        choices=TenancyStatus.choices,
        default=TenancyStatus.PENDING_NEGOTIATION,
    )

    # Financial terms — frozen copies of the property's values at tenancy creation.
    # If the landlord later edits the listing, existing tenancies are unaffected.
    monthly_rent = models.DecimalField(max_digits=10, decimal_places=2)
    advance_months = models.PositiveSmallIntegerField(
        validators=[MaxValueValidator(6)]
    )
    # advance_amount is stored, not computed. It appears on the Rent Card PDF
    # (a legal document). Computed values can change if monthly_rent is ever
    # corrected; a stored value is an immutable snapshot.
    advance_amount = models.DecimalField(max_digits=10, decimal_places=2)

    # Tenancy period
    start_date = models.DateField()
    end_date = models.DateField()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Tenancy"
        verbose_name_plural = "Tenancies"

    def __str__(self):
        return (
            f"Tenancy {self.id} — "
            f"{self.tenant.get_full_name()} @ "
            f"{self.rental_property.title}"
        )

    @property
    def is_pending_negotiation(self):
        return self.status == TenancyStatus.PENDING_NEGOTIATION

    @property
    def is_pending_agreement(self):
        return self.status == TenancyStatus.PENDING_AGREEMENT

    @property
    def is_pending_payment(self):
        return self.status == TenancyStatus.PENDING_PAYMENT

    @property
    def is_active(self):
        return self.status == TenancyStatus.ACTIVE

    @property
    def is_expiring(self):
        return self.status == TenancyStatus.EXPIRING

    @property
    def is_ended(self):
        return self.status == TenancyStatus.ENDED

    @property
    def total_rent(self):
        """Total contractual rent over the full lease term."""
        from dateutil.relativedelta import relativedelta
        delta = relativedelta(self.end_date, self.start_date)
        months = delta.years * 12 + delta.months
        return self.monthly_rent * months


class AgreementStatus(models.TextChoices):
    PENDING_LANDLORD = "pending_landlord", "Pending Landlord Confirmation"
    PENDING_TENANT   = "pending_tenant",   "Pending Tenant Confirmation"
    FULLY_EXECUTED   = "fully_executed",   "Fully Executed"


class Agreement(models.Model):
    """
    Created when a negotiation resolves (negotiations.accept_proposal(),
    not yet built — see handoff §16). Tracks the dual-OTP confirmation
    dance required before a Tenancy Agreement and Rent Card can be
    generated, per Act 220 Section 20.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenancy = models.OneToOneField(
        "Tenancy", on_delete=models.PROTECT, related_name="agreement"
    )
    status = models.CharField(
        max_length=20,
        choices=AgreementStatus.choices,
        default=AgreementStatus.PENDING_LANDLORD,
    )

    # Special conditions — raw input stored for audit, formalised version
    # (via Claude API, claude-sonnet-4-6) goes into the generated PDF.
    special_conditions_raw = models.TextField(blank=True)
    special_conditions     = models.TextField(blank=True)

    # OTP confirmation audit trail
    landlord_confirmed_at = models.DateTimeField(null=True, blank=True)
    landlord_otp_ref      = models.CharField(max_length=100, blank=True)
    tenant_confirmed_at   = models.DateTimeField(null=True, blank=True)
    tenant_otp_ref        = models.CharField(max_length=100, blank=True)
    fully_executed_at     = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Agreement"

    def __str__(self):
        return f"Agreement for Tenancy {self.tenancy_id} — {self.get_status_display()}"

    @property
    def is_fully_executed(self):
        return self.status == AgreementStatus.FULLY_EXECUTED
