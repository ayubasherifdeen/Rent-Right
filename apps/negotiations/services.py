from django.db import transaction
from django.utils import timezone

from apps.negotiations.models import Proposal, ProposalStatus


def open_negotiation(tenancy) -> Proposal:
    """
    Called explicitly from tenancies/services.py at the point a Tenancy
    enters PENDING_NEGOTIATION (mirrors the explicit-call pattern
    _execute_agreement() already uses for documents — not a signal).

    Creates the landlord's opening Proposal, pre-filled from the
    Listing's stated instalment terms.

    ASSUMED INTERFACE, NOT CONFIRMED — same category of risk as the
    verify_otp assumption flagged in handoff v8 §2.7. This reads
    `tenancy.rental_property.listing.default_advance_months`,
    `.default_instalment_count`, `.default_instalment_schedule` off the
    Listing. I don't have the real Listing model for this session, so
    these field names are a guess at the shape, not a confirmed
    interface. Adjust this function to match whatever the Listing
    actually calls its instalment terms before relying on it.
    """
    listing = tenancy.rental_property.listing

    with transaction.atomic():
        proposal = Proposal.objects.create(
            tenancy=tenancy,
            previous_proposal=None,
            proposed_by=tenancy.landlord,
            status=ProposalStatus.PENDING,
            advance_months=listing.default_advance_months,
            instalment_count=listing.default_instalment_count,
            instalment_schedule=listing.default_instalment_schedule,
        )
    return proposal


def counter_proposal(
    previous_proposal, proposed_by, advance_months, instalment_count, instalment_schedule
) -> Proposal:
    """
    Marks previous_proposal COUNTERED, creates a new PENDING Proposal
    chained to it.

    Raises ValueError if proposed_by is the same party who made
    previous_proposal — a party can only respond to the other side's
    proposal, never counter their own.
    """
    if proposed_by_id_matches(proposed_by, previous_proposal.proposed_by):
        raise ValueError("Cannot counter your own proposal.")

    if previous_proposal.status != ProposalStatus.PENDING:
        raise ValueError(
            f"Cannot counter a proposal with status "
            f"'{previous_proposal.status}' — only PENDING proposals can be countered."
        )

    with transaction.atomic():
        previous_proposal.status = ProposalStatus.COUNTERED
        previous_proposal.responded_at = timezone.now()
        previous_proposal.save(update_fields=["status", "responded_at"])

        new_proposal = Proposal.objects.create(
            tenancy=previous_proposal.tenancy,
            previous_proposal=previous_proposal,
            proposed_by=proposed_by,
            status=ProposalStatus.PENDING,
            advance_months=advance_months,
            instalment_count=instalment_count,
            instalment_schedule=instalment_schedule,
        )
    return new_proposal


def accept_proposal(proposal, accepted_by):
    """
    Marks proposal ACCEPTED, creates the Agreement for proposal.tenancy,
    and advances the tenancy out of PENDING_NEGOTIATION.

    Raises ValueError if accepted_by is the same party who made the
    proposal — can't accept your own offer.

    Deliberately does NOT copy advance_months / instalment_schedule onto
    Agreement — Agreement (per the real model, handoff v9) has no fields
    for those. The accepted Proposal remains the source of truth for
    instalment terms; anything needing them after acceptance should read
    tenancy.proposals.get(status=ProposalStatus.ACCEPTED), not Agreement.
    This is a product decision made in the absence of a confirmed §16
    spec — flagged, not silent — and is reversible (add fields + migrate
    + backfill this function) if that turns out to be wrong.

    Agreement is created with its model default status (PENDING_LANDLORD)
    — dual OTP confirmation and eventual PDF generation are unchanged,
    already-built downstream flow (apps.tenancies / apps.documents) and
    are not re-implemented here.
    """
    from apps.tenancies.models import Agreement, TenancyStatus

    if proposed_by_id_matches(accepted_by, proposal.proposed_by):
        raise ValueError("Cannot accept your own proposal.")

    if proposal.status != ProposalStatus.PENDING:
        raise ValueError(
            f"Cannot accept a proposal with status "
            f"'{proposal.status}' — only PENDING proposals can be accepted."
        )

    with transaction.atomic():
        proposal.status = ProposalStatus.ACCEPTED
        proposal.responded_at = timezone.now()
        proposal.save(update_fields=["status", "responded_at"])

        tenancy = proposal.tenancy
        agreement = Agreement.objects.create(tenancy=tenancy)

        tenancy.status = TenancyStatus.PENDING_AGREEMENT
        tenancy.save(update_fields=["status", "updated_at"])

    return agreement


def reject_proposal(proposal, rejected_by) -> None:
    """
    Marks proposal REJECTED. Terminal for this negotiation chain — does
    not create a new Proposal. What happens to the Tenancy after a
    rejection (stays PENDING_NEGOTIATION for a fresh opening proposal?
    something else?) is not decided here; out of scope for this pass,
    flagging rather than guessing at tenancy-level fallout.
    """
    if proposal.status != ProposalStatus.PENDING:
        raise ValueError(
            f"Cannot reject a proposal with status "
            f"'{proposal.status}' — only PENDING proposals can be rejected."
        )

    proposal.status = ProposalStatus.REJECTED
    proposal.responded_at = timezone.now()
    proposal.save(update_fields=["status", "responded_at"])


def get_current_proposal(tenancy):
    """The latest (most recent) Proposal in tenancy's chain, or None."""
    return tenancy.proposals.order_by("-created_at").first()


def get_proposal_chain(tenancy):
    """Full chain, oldest first — for negotiation history display."""
    return tenancy.proposals.order_by("created_at")


def proposed_by_id_matches(user_a, user_b) -> bool:
    """Small helper so the self-counter/self-accept guard compares by id,
    not object identity (proposed_by may be re-fetched)."""
    return user_a.pk == user_b.pk
