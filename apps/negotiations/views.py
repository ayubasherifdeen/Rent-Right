from django.contrib import messages

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponseBadRequest, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render

from apps.negotiations.models import Proposal
from apps.negotiations.services import accept_proposal, counter_proposal, reject_proposal


def _require_party_or_staff(user, tenancy):
    """
    Same access-control pattern as apps.documents.views.download_document:
    landlord-or-tenant-of-the-tenancy, or is_staff. 404 (not 403) for
    anyone else, so a stranger can't distinguish "doesn't exist" from
    "not yours."
    """
    if user.is_staff:
        return
    if user.pk in (tenancy.landlord_id, tenancy.tenant_id):
        return
    raise Http404


@login_required
def negotiation_detail(request, tenancy_id):
    """Current proposal + full chain for a tenancy's negotiation."""
    from apps.tenancies.models import Tenancy

    tenancy = get_object_or_404(Tenancy, pk=tenancy_id)
    _require_party_or_staff(request.user, tenancy)

    proposals = tenancy.proposals.order_by("created_at")
    current = tenancy.proposals.order_by("-created_at").first()

    return render(
        request,
        "negotiations/negotiation_detail.html",
        {"tenancy": tenancy, "proposals": proposals, "current_proposal": current},
    )


@login_required
def counter_proposal_view(request, proposal_id):
    """POST-only. Other party submits new instalment terms in response."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    proposal = get_object_or_404(Proposal, pk=proposal_id)
    _require_party_or_staff(request.user, proposal.tenancy)

    try:
        advance_months = int(request.POST["advance_months"])
        instalment_count = int(request.POST["instalment_count"])
    except (KeyError, ValueError, TypeError):
        return HttpResponseBadRequest("Invalid or missing proposal terms.")

    try:
        counter_proposal(
            previous_proposal=proposal,
            proposed_by=request.user,
            advance_months=advance_months,
            instalment_count=instalment_count,
        )
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("negotiations:negotiation_detail", tenancy_id=proposal.tenancy_id)
        
    messages.success(request, "Counter proposal submitted successfully.")
    return redirect("negotiations:negotiation_detail", tenancy_id=proposal.tenancy_id)


@login_required
def accept_proposal_view(request, proposal_id):
    """POST-only. Other party accepts terms as-is; creates the Agreement."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    proposal = get_object_or_404(Proposal, pk=proposal_id)
    _require_party_or_staff(request.user, proposal.tenancy)
    tenancy_id = proposal.tenancy_id

    try:
        accept_proposal(proposal, accepted_by=request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("negotiations:negotiation_detail", tenancy_id=proposal.tenancy_id)

    messages.success(request, "Offer accepted.")
    return redirect("tenancies:agreement_detail", pk=tenancy_id)


@login_required
def reject_proposal_view(request, proposal_id):
    """POST-only. Other party rejects terms outright."""
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    proposal = get_object_or_404(Proposal, pk=proposal_id)
    _require_party_or_staff(request.user, proposal.tenancy)

    try:
        reject_proposal(proposal, rejected_by=request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("negotiations:negotiation_detail", tenancy_id=proposal.tenancy_id)
    
    proposal.tenancy.refresh_from_db()

    from apps.tenancies.models import TenancyStatus

    if proposal.tenancy.status == TenancyStatus.CANCELLED:
        messages.info(
            request,
            "Offer rejected. This negotiation has gone through too many "
            "rounds without agreement and has been cancelled — the "
            "property is available for new applications again.",
        )
    else:
        messages.info(request, "Offer rejected. You can submit a counter-offer below.")

    return redirect("negotiations:negotiation_detail", tenancy_id=proposal.tenancy_id)
