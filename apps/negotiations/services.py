import re

from dateutil.relativedelta import relativedelta
from django.db import transaction
from django.utils import timezone
from datetime import date

from apps.accounts.services import send_tenancy_confirmation_otp
from apps.accounts.services import send_tenancy_confirmation_otp
from apps.listings.models import ACT_220_MAX_ADVANCE_MONTHS, PaymentCycle
from apps.negotiations.models import Proposal, ProposalStatus


MAX_NEGOTIATION_ROUNDS = 5

_CYCLE_INTERVAL_MONTHS = {
    PaymentCycle.MONTHLY: 1,
    PaymentCycle.QUARTERLY: 3,
    PaymentCycle.BIANNUAL: 6,
    PaymentCycle.ANNUAL: 12,
}


def _add_months(base_date, months):
    """Add N months to a date, clamping the day for shorter months
    (e.g. Jan 31 + 1 month -> Feb 28/29). No external dependency."""
    month_index = base_date.month - 1 + months
    year = base_date.year + month_index // 12
    month = month_index % 12 + 1
    days_in_month = [
        31,
        29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28,
        31, 30, 31, 30, 31, 31, 30, 31, 30, 31,
    ]
    day = min(base_date.day, days_in_month[month - 1])
    return date(year, month, day)


def _build_default_instalment_schedule(tenancy, advance_months, instalment_count):
    """
    Splits lease term remaiing after advance and covers whats left
    """
    delta = relativedelta(tenancy.end_date, tenancy.start_date)
    lease_term_months = delta.years * 12 + delta.months
    remaining_months =max(lease_term_months - advance_months, 0)

    if instalment_count <= 0 or remaining_months <= 0:
        return []
    
    remaining_rent = tenancy.monthly_rent * remaining_months

    interval_months = max(remaining_months // instalment_count, 1)
    amount_per_instalment = (remaining_rent / instalment_count).quantize(
        tenancy.monthly_rent
    )


    schedule = []
    for i in range(instalment_count):
        due = _add_months(tenancy.start_date, advance_months + interval_months * (i + 1))
        schedule.append({"due_date": due.isoformat(), "amount": str(amount_per_instalment)})
    return schedule

def _default_instalment_count(rental_property, tenancy, advance_months):
    """Payment-cycle-derived default count for the opening Proposal — based
    on months remaining after advance"""
    interval_months = _CYCLE_INTERVAL_MONTHS.get(rental_property.payment_cycle, 12)
    delta = relativedelta(tenancy.end_date, tenancy.start_date)
    lease_term_months = delta.years * 12 + delta.months
    remaining_months = max(lease_term_months - advance_months, 0)
    if remaining_months <= 0:
        return 0
    return max(remaining_months // interval_months, 1)

def open_negotiation(tenancy) -> Proposal:
    """
    Creates the landlord's opening Proposal, pre-filled from the
    Listing's stated instalment terms.

    called from tenancies/services when new tenancy is created
    """
    rental_property = tenancy.rental_property
    instalment_count = _default_instalment_count(rental_property, tenancy, tenancy.advance_months)

    with transaction.atomic():
        proposal = Proposal.objects.create(
            tenancy=tenancy,
            previous_proposal=None,
            proposed_by=tenancy.landlord,
            status=ProposalStatus.PENDING,
            advance_months=rental_property.advance_months,
            instalment_count=instalment_count,
            instalment_schedule=_build_default_instalment_schedule(tenancy, rental_property.advance_months, instalment_count),
        )
    return proposal


def _cancel_negotiation(tenancy):
    """
    Shared by counter_proposal() and reject_proposal() — cancels the
    tenancy and reopens the property. Caller is responsible for wrapping
    this in transaction.atomic() alongside whatever else needs to commit
    together.
    """
    from apps.listings.models import ListingStatus
    from apps.tenancies.models import TenancyStatus

    tenancy.status = TenancyStatus.CANCELLED
    tenancy.save(update_fields=["status", "updated_at"])

    rental_property = tenancy.rental_property
    rental_property.status = ListingStatus.LIVE
    rental_property.save(update_fields=["status", "updated_at"])


def counter_proposal(
    previous_proposal, proposed_by, advance_months, instalment_count
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
    
    if advance_months < 1 or advance_months > ACT_220_MAX_ADVANCE_MONTHS:
        raise ValueError(
            f"Advance months must be between 1 and {ACT_220_MAX_ADVANCE_MONTHS} "
            f"per Section 25(5) of Act 220. Got {advance_months}."
        )
    if instalment_count < 0:
        raise ValueError("Instalment cannot be negative.")

    from apps.tenancies.models import TenancyStatus

    if previous_proposal.status not in (ProposalStatus.PENDING, ProposalStatus.REJECTED):
        raise ValueError(
            f"Cannot counter a proposal with status "
            f"'{previous_proposal.status}' — only PENDING or REJECTED "
            f"proposals can be countered."
        )

    if previous_proposal.tenancy.status == TenancyStatus.CANCELLED:
        raise ValueError(
            "This negotiation has been cancelled after too many rounds "
            "without agreement — no further counters possible."
        )
    
    if previous_proposal.tenancy.proposals.count() >= MAX_NEGOTIATION_ROUNDS:
        with transaction.atomic():
            _cancel_negotiation(previous_proposal.tenancy)
        raise ValueError(
            f"This negotiation has reached the maximum of "
            f"{MAX_NEGOTIATION_ROUNDS} rounds without agreement and has "
            f"been cancelled. The property is available for new "
            f"applications again."
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
            instalment_schedule=_build_default_instalment_schedule(previous_proposal.tenancy,advance_months, instalment_count),
        )
    return new_proposal


def accept_proposal(proposal, accepted_by):
    """
    Marks proposal ACCEPTED, creates the Agreement for proposal.tenancy,
    and advances the tenancy out of PENDING_NEGOTIATION.

    Raises ValueError if accepted_by is the same party who made the
    proposal — can't accept your own offer.

    Deliberately does NOT copy advance_months / instalment_schedule onto
    Agreement — Agreement has no fields
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

    send_tenancy_confirmation_otp(tenancy.landlord)
    send_tenancy_confirmation_otp(tenancy.tenant)

    # TODO: Call notifications.tasks.send_sms.delay(...) for both — same
    # stub gap as everywhere else OTPs are sent; codes currently only
    # reach logger.debug() until the notifications app exists.

    return agreement


def reject_proposal(proposal, rejected_by) -> None:
    """
    Marks proposal REJECTED. Terminal for this negotiation chain — does
    not create a new Proposal. What happens to the Tenancy after a
    rejection (stays PENDING_NEGOTIATION for a fresh opening proposal?
    something else?) is not decided here; out of scope for this pass,
    flagging rather than guessing at tenancy-level fallout.
    """
    from apps.tenancies.models import TenancyStatus
    if proposed_by_id_matches(rejected_by, proposal.proposed_by):
        raise ValueError("Cannot reject your own proposal.")

    if proposal.status != ProposalStatus.PENDING:
        raise ValueError(
            f"Cannot reject a proposal with status "
            f"'{proposal.status}' — only PENDING proposals can be rejected."
        )

    with transaction.atomic():
        proposal.status = ProposalStatus.REJECTED
        proposal.responded_at = timezone.now()
        proposal.save(update_fields=["status", "responded_at"])

        tenancy = proposal.tenancy
        
        round_count = tenancy.proposals.count()
        if round_count >= MAX_NEGOTIATION_ROUNDS:
            _cancel_negotiation(tenancy)
        
    return proposal



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
