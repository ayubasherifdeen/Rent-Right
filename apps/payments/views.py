import json

from django.contrib.auth.decorators import login_required
from django.http import (
    Http404,
    HttpResponse,
    HttpResponseBadRequest,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.tenancies.models import Tenancy
from apps.listings.models import ListingStatus

from . import services
from apps.documents.services import get_documents_for
from .models import PaymentType, PaymentStatus
from apps.documents.models import DocumentType


def _tenancy_for_party_or_404(pk, user):
    tenancy = get_object_or_404(Tenancy, pk=pk)
    if user != tenancy.tenant and user != tenancy.landlord and not user.is_staff:
        raise Http404
    return tenancy


@login_required
def initiate_move_in_payment_view(request, pk):
    tenancy = get_object_or_404(Tenancy, pk=pk, tenant=request.user)
    callback_url = request.build_absolute_uri(reverse("payments:payment_callback"))
    try:
        payment, authorization_url = services.initiate_payment(
            tenancy, request.user, PaymentType.MOVE_IN, callback_url
        
        )
    except (ValueError, services.PaystackError) as exc:
        return render(
            request, "payments/payment_error.html", {"error": str(exc), "tenancy": tenancy}
        )
    return redirect(authorization_url)


@login_required
def initiate_instalment_payment_view(request, pk, due_date):
    """
    due_date arrives as a URL string (YYYY-MM-DD) matching an entry in
    the accepted Proposal's instalment_schedule — see
    services.initiate_payment()'s guard for what happens if it doesn't
    match anything.
    """
    tenancy = get_object_or_404(Tenancy, pk=pk, tenant=request.user)
    callback_url = request.build_absolute_uri(reverse("payments:payment_callback"))
    try:
        payment, authorization_url = services.initiate_payment(
            tenancy,
            request.user,
            PaymentType.INSTALMENT,
            callback_url,
            instalment_due_date=due_date,
        )
    except (ValueError, services.PaystackError) as exc:
        return render(
            request, "payments/payment_error.html", {"error": str(exc), "tenancy": tenancy}
        )
    return redirect(authorization_url)


def payment_callback_view(request):
    """
    Where Paystack redirects the payer's browser after checkout
    (success or failure/cancel — Paystack sends the same callback_url
    either way). UX-only: re-verifies via
    services.verify_and_record_payment() rather than trusting the query
    string, so this can't be used to fake a successful payment by
    hand-editing the URL. Not login_required — the payer's session may
    have lapsed during the redirect round-trip to Paystack's domain and
    back; the reference itself (a UUID) is the actual authorization.
    """
    reference = request.GET.get("reference") or request.GET.get("trxref")
    if not reference:
        return HttpResponseBadRequest("Missing payment reference.")
    try:
        payment = services.verify_and_record_payment(reference)
    except (ValueError, services.PaystackError) as exc:
        return render(request, "payments/payment_error.html", {"error": str(exc)})
    return render(request, "payments/payment_result.html",
                  {"payment": payment,
                    "receipt": get_documents_for(payment).first()
                })


@csrf_exempt
@require_POST
def paystack_webhook_view(request):
    """
    Server-to-server — this is the AUTHORITATIVE path for activating a
    tenancy / generating a receipt, not the browser callback above.
    CSRF-exempt because Paystack isn't a browser session; authenticated
    instead via the X-Paystack-Signature HMAC check.

    Returns 200 even when the downstream verify call fails, on purpose
    — Paystack retries on non-2xx responses, and a hiccup on our end
    talking to Paystack's own verify endpoint shouldn't trigger repeated
    retries for an event that was itself received and authenticated
    correctly. The failure is still visible: verify_and_record_payment()
    leaves the Payment row's status untouched (still PENDING) rather
    than marking anything falsely successful.
    """
    signature = request.headers.get("X-Paystack-Signature", "")
    if not services.verify_webhook_signature(request.body, signature):
        return HttpResponse(status=401)

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponseBadRequest()

    if payload.get("event") == "charge.success":
        reference = payload.get("data", {}).get("reference")
        if reference:
            try:
                services.verify_and_record_payment(reference)
            except (ValueError, services.PaystackError):
                pass  # see docstring — logged inside the service layer

    return JsonResponse({"received": True})


@login_required
def payments_dashboard_view(request):
    """
    Landing page for the navbar's "Payments" tab. Two different views
    depending on role — a tenant cares about what THEY owe (move-in due,
    next instalment due); a landlord cares about what's been RECEIVED
    and which tenants are overdue. A user who is both a landlord on some
    properties and a tenant on others (not disallowed anywhere in the
    models) sees both sections.
 
    ASSUMPTION FLAGGED: I don't have your navbar template or an existing
    aggregate tenancies list (my_tenancies.html / landlord_tenancies.html)
    to confirm the query pattern against — this re-derives "tenancies I'm
    a tenant/landlord on" directly from Tenancy rather than reusing a
    helper that may already exist there. If tenancies/services.py has
    something like get_tenant_tenancies()/get_landlord_tenancies(),
    swap these two queries for that instead of duplicating the logic.
    """
    from apps.tenancies.models import Tenancy, TenancyStatus
 
    tenant_rows = []
    as_tenant = Tenancy.objects.filter(tenant=request.user).exclude(
        status=TenancyStatus.CANCELLED
    ).select_related("rental_property")
    for tenancy in as_tenant:
        if tenancy.status not in (TenancyStatus.PENDING_PAYMENT, TenancyStatus.ACTIVE):
            continue  # nothing payment-related to show pre-agreement or post-tenancy
        move_in_payment = (
            tenancy.payments.filter(payment_type=PaymentType.MOVE_IN)
            .order_by("-created_at")
            .first()
        )
        next_due = None
        if tenancy.status == TenancyStatus.ACTIVE:
            schedule = services.get_instalment_schedule_with_status(tenancy)
            next_due = next((row for row in schedule if row["status"] != "paid"), None)
        tenant_rows.append(
            {"tenancy": tenancy, "move_in_payment": move_in_payment, "next_due": next_due}
        )
 
    landlord_rows = []
    as_landlord = Tenancy.objects.filter(landlord=request.user).exclude(
        status=TenancyStatus.CANCELLED
    ).select_related("rental_property")
    for tenancy in as_landlord:
        if tenancy.status not in (TenancyStatus.PENDING_PAYMENT, TenancyStatus.ACTIVE):
            continue
        overdue = services.get_overdue_instalments(tenancy) if tenancy.status == TenancyStatus.ACTIVE else []
        move_in_paid = tenancy.payments.filter(
            payment_type=PaymentType.MOVE_IN, status=PaymentStatus.SUCCESS
        ).exists()
        landlord_rows.append(
            {"tenancy": tenancy, "move_in_paid": move_in_paid, "overdue_count": len(overdue)}
        )
 
    return render(
        request,
        "payments/payments_dashboard.html",
        {"tenant_rows": tenant_rows, "landlord_rows": landlord_rows},
    )


@login_required
def payment_history_view(request, pk):
    tenancy = _tenancy_for_party_or_404(pk, request.user)
    schedule = services.get_instalment_schedule_with_status(tenancy)
    move_in_payment = (
        tenancy.payments.filter(payment_type=PaymentType.MOVE_IN).order_by("-created_at").first()
    )
    move_in_receipt = get_documents_for(move_in_payment).first() if move_in_payment else None
    for row in schedule:
        row["receipt"] = get_documents_for(row["payment"]).first() if row["payment"] else None

    rent_cards = list(
        get_documents_for(tenancy).filter(document_type=DocumentType.RENT_CARD).order_by("generated_at")
    )
    successful_payments = list(tenancy.payments.filter(status=PaymentStatus.SUCCESS).order_by("paid_at"))
    rent_card_by_payment = dict(zip(successful_payments, rent_cards))

    move_in_rent_card = rent_card_by_payment.get(move_in_payment) if move_in_payment else None
    for row in schedule:
        row["receipt"] = get_documents_for(row["payment"]).first() if row["payment"] else None
        row["rent_card"] = rent_card_by_payment.get(row["payment"]) if row["payment"] else None

    return render(
        request,
        "payments/payment_history.html",
        {"tenancy": tenancy,
         "schedule": schedule,
         "move_in_payment": move_in_payment,
         "move_in_receipt":move_in_receipt,
         "move_in_rent_card": move_in_rent_card,
         "latest_rent_card": rent_cards[-1] if rent_cards else None
         },

    )
