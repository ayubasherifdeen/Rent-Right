import uuid

from django.conf import settings
from django.db import models


class ProposalStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    COUNTERED = "countered", "Countered"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"


class Proposal(models.Model):
    """
    One step in a bilateral instalment negotiation for a Tenancy.

    Immutable chain, not a mutated single row: every counter creates a
    new Proposal linked back to the one it responds to via
    `previous_proposal`. This is deliberate — it gives full negotiation
    history "for free" (needed later for documents.generate_dispute_packet(),
    per handoff v9 §4), rather than something that would need to be
    reconstructed after the fact.

    Only instalment structure is negotiable here — `monthly_rent` is
    fixed from the Listing/Property and is never touched by this app.
    `advance_months` is a real field (not just JSON) specifically so
    Section 25(5)'s 6-month advance cap can be validated against it
    directly.

    accept_proposal() is the handoff into the Agreement lifecycle
    (apps.tenancies). Note Agreement itself carries no instalment
    fields — the accepted Proposal remains the source of truth for
    those terms; anything reading instalment data after acceptance
    (e.g. apps.documents.generate_tenancy_agreement) goes through
    tenancy.proposals.get(status=ProposalStatus.ACCEPTED), not through
    Agreement. See handoff discussion for why (no confirmed §16 spec
    to source an alternative from).
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
    advance_months = models.PositiveSmallIntegerField()  # must stay <= 6, Section 25(5)
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
