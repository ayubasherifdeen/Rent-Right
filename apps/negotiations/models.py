import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


from apps.listings.models import ACT_220_MAX_ADVANCE_MONTHS

class ProposalStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    COUNTERED = "countered", "Countered"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"


class Proposal(models.Model):
    """
    One step in a bilateral instalment negotiation for a Tenancy.

    Immutable chain: every counter creates a
    new Proposal linked back to the one it responds to via
    `previous_proposal`to give full negotiation
    history "for free" (needed later for documents.generate_dispute_packet()),
    rather than something that would need to be
    reconstructed after the fact.

    Only instalment structure is negotiable here — `monthly_rent` is
    fixed from the Listing/Property and is never touched by this app.
    `advance_months` is a real field (not just JSON) specifically so
    Section 25(5)'s 6-month advance cap can be validated against it
    directly.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenancy = models.ForeignKey(
        "tenancies.Tenancy", on_delete=models.CASCADE, related_name="proposals"
    )
    previous_proposal = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="countered_by",
    )
    proposed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    status = models.CharField(
        max_length=16, choices=ProposalStatus.choices, default=ProposalStatus.PENDING
    )

    # Instalment terms only — monthly_rent is never touched by this app.
    advance_months = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(ACT_220_MAX_ADVANCE_MONTHS)],
        help_text=(
            f"Maximum {ACT_220_MAX_ADVANCE_MONTHS} months per Section 25(5) of Act 220."
        ),
    )
    instalment_count = models.PositiveSmallIntegerField()
    instalment_schedule = models.JSONField()  # [{"due_date": ..., "amount": ...}, ...]

    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Proposal"

    def __str__(self):
        return f"Proposal for Tenancy {self.tenancy_id} — {self.get_status_display()}"

    @property
    def is_opening_proposal(self):
        return self.previous_proposal_id is None
    
    def clean(self):
        """
        Second layer of Section 25(5) enforcement, same reasoning as
        Property.clean(): catches anything that bypasses the field
        validator (bulk updates, admin edits, direct .save() calls that
        skip full_clean()).
        """
        errors = {}
        if self.advance_months and self.advance_months > ACT_220_MAX_ADVANCE_MONTHS:
            errors["advance_months"] = (
                f"Advance rent cannot exceed {ACT_220_MAX_ADVANCE_MONTHS} months "
                f"under Section 25(5) of the Rent Act, 1963 (Act 220). "
                f"You entered {self.advance_months} months."
            )
        if errors:
            raise ValidationError(errors)

