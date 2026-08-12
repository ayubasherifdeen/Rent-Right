"""
Guard pattern (mirrors applications app):
  - ValueError from services → flash message + redirect (not 403/500)
  - Ownership verified inside the service, not duplicated in the view

"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from django.http import HttpResponseForbidden, HttpResponseNotAllowed

from apps.accounts.decorators import landlord_required, tenant_required
from apps.accounts.services import send_tenancy_confirmation_otp
from apps.applications.models import Application
from apps.documents.models import DocumentType
from apps.documents.services import get_documents_for, get_latest_document
from apps.payments.models import PaymentType
from apps.tenancies.models import Agreement, Tenancy
from django.db.models import Count, Q
from apps.tenancies.models import TenancyStatus
from apps.tenancies.services import (
    activate_tenancy,
    confirm_agreement_landlord,
    confirm_agreement_tenant,
    create_tenancy,
    formalise_special_conditions,
    save_special_conditions,
)


# Landlord: create a tenancy from an approved application

@landlord_required
def create_tenancy_view(request, application_pk):
    """
    POST only. Landlord-initiated. Triggered from the 'Create Tenancy'
    on received_applications.html once an application is APPROVED.
    """
    if request.method != "POST":
        return redirect("applications:received_applications")

    application = get_object_or_404(Application, pk=application_pk)

    try:
        tenancy = create_tenancy(application, landlord=request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("applications:received_applications")

    messages.success(
        request,
        "Tenancy created and opened for negotiation.",
    )
    return redirect("tenancies:tenancy_detail", pk=tenancy.pk)


# Landlord: activate a tenancy (PENDING_PAYMENT -> ACTIVE)
@landlord_required
def activate_tenancy_view(request, pk):
    """
    POST only. Manually advances status to ACTIVE.
    will be replaced by automatic Paystack webhook trigger.
    """
    if request.method != "POST":
        return redirect("tenancies:tenancy_detail", pk=pk)

    tenancy = get_object_or_404(Tenancy, pk=pk)

    try:
        activate_tenancy(tenancy, landlord=request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("tenancies:tenancy_detail", pk=pk)

    messages.success(request, "Tenancy activated successfully.")
    return redirect("tenancies:tenancy_detail", pk=pk)


# Shared: tenancy detail (landlord or tenant of this tenancy)

@login_required
def tenancy_detail(request, pk):
    """
    every document generic-FK'd to this Tenancy (i.e. its Rent Card, once
    generated). Will be an empty queryset until the tenancy's Agreement
    is fully executed, since that's the only place generate_rent_card()
    is currently called (_execute_agreement()). tenancy_detail.html
    still needs updating to actually render this — not done here, no
    template file for this session.
    """
    from apps.negotiations.services import get_current_proposal
    tenancy = get_object_or_404(Tenancy, pk=pk)

    from apps.payments.models import Payment, PaymentType
    from apps.payments.services import get_instalment_schedule_with_status

    move_in_payment = tenancy.payments.filter(payment_type=PaymentType.MOVE_IN).order_by("-created_at").first()
    next_due_instalment = None
    if tenancy.status == "active":
        schedule = get_instalment_schedule_with_status(tenancy)
        next_due_instalment = next((row for row in schedule if row["status"] != "paid"), None)


    # Only the landlord or tenant party to this specific tenancy may view it.
    if request.user not in (tenancy.landlord, tenancy.tenant):
        raise Http404

    context = {
        "tenancy": tenancy,
        "is_landlord": request.user == tenancy.landlord,
        "agreement": getattr(tenancy, "agreement", None),
        "current_proposal": get_current_proposal(tenancy),
        "documents": get_documents_for(tenancy),
        "move_in_payment": move_in_payment,
        "next_due_instalment": next_due_instalment,
        "current_rent_card": get_latest_document(tenancy, DocumentType.RENT_CARD),
    }
    return render(request, "tenancies/tenancy_detail.html", context)


# Tenant: list own tenancies
@tenant_required
def my_tenancies(request):
    tenancies = (
        Tenancy.objects.filter(tenant=request.user)
        .select_related("rental_property", "landlord")
        .order_by("-created_at")
    )
    return render(request, "tenancies/my_tenancies.html", {"tenancies": tenancies})


# Landlord: list all tenancies across owned properties
@landlord_required
def landlord_tenancies(request):
    tenancies = (
        Tenancy.objects.filter(landlord=request.user)
        .select_related("rental_property", "tenant")
        .order_by("-created_at")
    )
    counts = tenancies.aggregate(
        total=Count("id"),
        active=Count("id", filter=Q(status=TenancyStatus.ACTIVE)),
        pending_payment=Count("id", filter=Q(status=TenancyStatus.PENDING_PAYMENT)),
    )
    return render(
        request, 
        "tenancies/landlord_tenancies.html",
        {"tenancies": tenancies, "counts":counts}
    )


# Landlord: enter + review special conditions for an agreement

@landlord_required
def special_conditions_view(request, pk):
    """
    GET: show the special-conditions entry/review form.
    POST (no 'confirm'): formalise_special_conditions() and show a
        review step — nothing is saved yet.
    POST (with 'confirm'): save the raw + formalised text the landlord
        just reviewed.
    """
    tenancy = get_object_or_404(Tenancy, pk=pk)
    if tenancy.landlord != request.user:
        raise Http404

    agreement = get_object_or_404(Agreement, tenancy=tenancy)

    formalised_preview = None
    raw_text = agreement.special_conditions_raw

    if request.method == "POST":
        raw_text = request.POST.get("raw_text", "")

        if request.POST.get("confirm"):
            formalised_text = request.POST.get("formalised_text", "")
            save_special_conditions(agreement, raw_text, formalised_text)
            messages.success(request, "Special conditions added and saved to the agreement.")
            return redirect("tenancies:agreement_detail", pk=tenancy.pk)

        formalised_preview = formalise_special_conditions(raw_text)

    context = {
        "tenancy": tenancy,
        "agreement": agreement,
        "raw_text": raw_text,
        "formalised_preview": formalised_preview,
    }
    return render(request, "tenancies/special_conditions.html", context)


@login_required
@require_POST
def request_agreement_otp_view(request, pk):
    tenancy = get_object_or_404(Tenancy, pk=pk)
    if request.user not in (tenancy.landlord, tenancy.tenant):
        raise Http404

    # Confirm an Agreement actually exists before sending a code for it —
    # otherwise a party could request one before negotiation has even
    # resolved.
    get_object_or_404(Agreement, tenancy=tenancy)

    send_tenancy_confirmation_otp(request.user)
    # TODO: Call notifications.tasks.send_sms.delay(...) — same stub gap
    # as resend_verification_otp, not new to this change.
    messages.info(request, "A confirmation code has been sent to your phone.")
    return redirect("tenancies:agreement_detail", pk=pk)
# Shared: OTP confirmation for either party

@login_required
def confirm_agreement_view(request, pk):
    """POST only. OTP entry for either party on this tenancy's agreement."""
    tenancy = get_object_or_404(Tenancy, pk=pk)
    if request.user not in (tenancy.landlord, tenancy.tenant):
        raise Http404

    agreement = get_object_or_404(Agreement, tenancy=tenancy)

    if request.method != "POST":
        return redirect("tenancies:agreement_detail", pk=pk)

    otp_code = request.POST.get("otp_code", "")

    try:
        if request.user == tenancy.landlord:
            confirm_agreement_landlord(agreement, request.user, otp_code)
        else:
            confirm_agreement_tenant(agreement, request.user, otp_code)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("tenancies:agreement_detail", pk=pk)

    agreement.refresh_from_db()
    if agreement.is_fully_executed:
        messages.success(request, "Agreement fully executed by both parties.")
    else:
        messages.success(request, "Confirmed. Waiting on the other party.")
    return redirect("tenancies:agreement_detail", pk=pk)


# Shared: agreement status + special conditions + OTP confirmation entry point

@login_required
def agreement_detail(request, pk):
    """
    passes `documents` — the Rent
    Card (generic-FK'd to the Tenancy) and Tenancy Agreement PDF
    (generic-FK'd to the Agreement) combined into one list, newest
    first. Empty until _execute_agreement() has run. agreement_detail.html
    still needs updating to actually render download links — not done
    here

    Also still needs updating (not done here) to render the new
    "Request Code" button (POSTs to tenancies:request_agreement_otp)
    alongside the existing OTP-entry form.
    """
    tenancy = get_object_or_404(Tenancy, pk=pk)
    if request.user not in (tenancy.landlord, tenancy.tenant):
        raise Http404

    agreement = get_object_or_404(Agreement, tenancy=tenancy)

    documents = sorted(
        list(get_documents_for(tenancy)) + list(get_documents_for(agreement)),
        key=lambda doc: doc.generated_at,
        reverse=True,
    )

    context = {
        "tenancy": tenancy,
        "agreement": agreement,
        "is_landlord": request.user == tenancy.landlord,
        "documents": documents,
    }
    return render(request, "tenancies/agreement_detail.html", context)


@login_required
def generate_dispute_packet_view(request, tenancy_id):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
 
    tenancy = get_object_or_404(Tenancy, pk=tenancy_id)
 
    if request.user.pk not in (tenancy.landlord_id, tenancy.tenant_id):
        return HttpResponseForbidden(
            "Only the landlord or tenant on this tenancy can generate a dispute packet."
        )
 
    from apps.documents.services import generate_dispute_packet
 
    document = generate_dispute_packet(
        tenancy,
        generated_by=request.user,
        dispute_summary=request.POST.get("dispute_summary", "").strip(),
    )
    messages.success(request, "Dispute packet generated.")
    return redirect("documents:download", document.id)
