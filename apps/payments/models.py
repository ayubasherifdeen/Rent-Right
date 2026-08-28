import uuid

from django.conf import settings
from django.db import models


class PaymentType(models.TextChoices):
    MOVE_IN    = "move_in",    "Move-in Payment"
    INSTALMENT = "instalment", "Instalment Payment"


class PaymentStatus(models.TextChoices):
    """
    Mirrors Paystack's own transaction status strings directly (rather
    than inventing RentRight-specific names) so verify_and_record_payment()
    can set this field straight from Paystack's response without a
    translation table that could drift out of sync with what Paystack
    actually returns.
    """
    PENDING   = "pending",   "Pending"
    SUCCESS   = "success",   "Success"
    FAILED    = "failed",    "Failed"
    ABANDONED = "abandoned", "Abandoned"

class PayoutMethod(models.TextChoices):
    BANK          = "bank",          "Bank Account"
    MOBILE_MONEY  = "mobile_money",  "Mobile Money"


class LandlordPayoutAccount(models.Model):
    """
    Where a landlord's share of tenant payments actually settles — one
    per landlord
    """
 
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    landlord = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="payout_account"
    )
 
    method = models.CharField(max_length=16, choices=PayoutMethod.choices)
    bank_code = models.CharField(max_length=20)     # Paystack settlement_bank code
    bank_name = models.CharField(max_length=100)    # display only, e.g. "MTN Mobile Money"
    account_number = models.CharField(max_length=20)  # bank account number OR MoMo phone number
 
    # Resolved from Paystack's Resolve Account Number endpoint, shown to
    # the landlord for confirmation BEFORE this row (or a subaccount) is
    # created — see services.resolve_account_number()'s docstring for why.
    account_name = models.CharField(max_length=150)
 
    paystack_subaccount_code = models.CharField(max_length=100, blank=True)
 
    # Platform's cut of every split transaction. Set from
    # settings.PLATFORM_FEE_PERCENTAGE at creation time, NOT landlord-
    # editable — this is a business decision, not something a payout
    # form should let someone type into.
    percentage_charge = models.DecimalField(max_digits=5, decimal_places=2)
 
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
 
    class Meta:
        verbose_name = "Landlord Payout Account"
 
    def __str__(self):
        return f"{self.landlord} — {self.get_method_display()} ({self.account_name})"
 
    @property
    def is_ready(self):
        return bool(self.paystack_subaccount_code)
 
    @property
    def is_stale(self):
        """
        Paystack subaccounts
        don't update themselves when a User row changes elsewhere, so
        this is what the dashboard checks to prompt a re-verify instead
        of silently paying out to a number the landlord no longer uses.
        """
        return self.is_ready and self.account_number != self.landlord.phone_number
 

class Payment(models.Model):
    """
    One Paystack transaction attempt: either the move-in advance or a
    single negotiated instalment.

    There's no per-instalment database row anywhere upstream:
    negotiations.Proposal.instalment_schedule is a plain JSONField list
    ([{"due_date": ..., "amount": ...}, ...]), not a set of
    ProposalInstalment rows (that model existed only in the v7 spec —
    the app actually built in v10 collapsed it into JSON on Proposal).
    So this model carries its own instalment_due_date / amount snapshot
    rather than FK'ing to a schedule entry that doesn't exist as a row.
    Matching an instalment Payment back to "which schedule entry is
    this" is done by due_date equality — see
    services.get_instalment_schedule_with_status().
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    tenancy = models.ForeignKey(
        "tenancies.Tenancy", on_delete=models.PROTECT, related_name="payments"
    )
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payments_made"
    )

    payment_type = models.CharField(max_length=16, choices=PaymentType.choices)
    status = models.CharField(
        max_length=16, choices=PaymentStatus.choices, default=PaymentStatus.PENDING
    )

    # Snapshot of what was actually invoiced to Paystack at
    # initiate_payment() time
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    instalment_due_date = models.DateField(null=True, blank=True)  # null for MOVE_IN

    # Paystack identifiers / audit trail
    reference = models.CharField(max_length=100, unique=True)  # our ref, sent to Paystack
    paystack_transaction_id = models.CharField(max_length=100, blank=True)
    channel = models.CharField(max_length=20, blank=True)  # 'mobile_money' / 'card' / ...
    gateway_response = models.JSONField(null=True, blank=True)  # raw verify payload

    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Payment"

    def __str__(self):
        return f"{self.get_payment_type_display()} — {self.tenancy_id} — {self.get_status_display()}"

    @property
    def is_successful(self):
        return self.status == PaymentStatus.SUCCESS
