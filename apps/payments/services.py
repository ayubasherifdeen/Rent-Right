"""
Paystack integration + payment state.

No Paystack account exists yet (per your note), so nothing in this file
has been exercised against the real API — it's written to Paystack's
documented /transaction/initialize, /transaction/verify, and webhook
signature contract, but flag this whole file for a real test pass with
test keys before relying on it. See handoff v12 §open items.
"""

from decimal import Decimal
import hashlib
import hmac
import json
import uuid
from datetime import date

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.documents.services import _financial_display_context, _get_accepted_proposal, generate_rent_card
from apps.notifications.models import NotificationPurpose
from apps.notifications.services import notify_user

from .models import Payment, PaymentStatus, PaymentType, PayoutMethod, LandlordPayoutAccount

PAYSTACK_BASE_URL = "https://api.paystack.co"


GHANA_MOMO_PREFIXES = {
    "024": "MTN", "025": "MTN", "053": "MTN", "054": "MTN", "055": "MTN", "059": "MTN",
    "020": "Telecel", "050": "Telecel",
    "026": "AirtelTigo", "027": "AirtelTigo", "056": "AirtelTigo", "057": "AirtelTigo",
}


class PaystackError(Exception):
    """Raised when Paystack's API returns a non-success response, or is unreachable."""
# Paystack API wrappers
def _paystack_secret_key():
    key = getattr(settings, "PAYSTACK_SECRET_KEY", "")
    if not key:
        raise PaystackError(
            "PAYSTACK_SECRET_KEY is not configured. Payments cannot be "
            "processed until a Paystack account exists and the key is "
            "added to settings/.env."
        )
    return key


def _paystack_headers():
    return {
        "Authorization": f"Bearer {_paystack_secret_key()}",
        "Content-Type": "application/json",
    }


def _paystack_initialize_transaction(*, email, amount, reference, callback_url, subaccount=None):
    """
    POST /transaction/initialize. `amount` is in GHS (Decimal/float);
    Paystack wants the smallest currency unit (pesewas), so the *100
    conversion happens here, in one place, rather than every caller
    doing its own.
    """
    payload = {
        "email": email,
        "amount": int(round(float(amount) * 100)),
        "reference": reference,
        "callback_url": callback_url,
        "currency": "GHS",
        "channels": ["mobile_money"],
    }
    if subaccount:
        payload["subaccount"] = subaccount
    try:
        resp = requests.post(
            f"{PAYSTACK_BASE_URL}/transaction/initialize",
            json=payload,
            headers=_paystack_headers(),
            timeout=15,
        )
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise PaystackError(f"Could not reach Paystack: {exc}") from exc

    if not resp.ok or not data.get("status"):
        raise PaystackError(data.get("message", "Paystack initialize failed."))

    return data["data"]  # {"authorization_url", "access_code", "reference"}


def list_ghana_momo_networks():
    """
    GET /bank?country=ghana&type=... — used to populate the payout-setup
    form's dropdown. 'ghipss' returns real Ghanaian banks; 'mobile_money'
    returns MTN Mobile Money / Telecel Cash / AirtelTigo Money, each
    with their own settlement_bank code, same shape as a real bank code.
    """
    try:
        resp = requests.get(
            f"{PAYSTACK_BASE_URL}/bank",
            params={"country": "ghana", "type": "mobile_money"},
            headers=_paystack_headers(),
            timeout=15,
        )
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise PaystackError(f"Could not reach Paystack: {exc}") from exc
    if not resp.ok or not data.get("status"):
        raise PaystackError(data.get("message", "Could not fetch bank/network list."))
    return [{"name": b["name"], "code": b["code"]} for b in data["data"]]
 
 

 
 
def _paystack_create_subaccount(*, business_name, settlement_bank, account_number, percentage_charge):
    payload = {
        "business_name": business_name,
        "settlement_bank": settlement_bank,
        "account_number": account_number,
        "percentage_charge": percentage_charge,
    }
    try:
        resp = requests.post(
            f"{PAYSTACK_BASE_URL}/subaccount", json=payload, headers=_paystack_headers(), timeout=15
        )
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise PaystackError(f"Could not reach Paystack: {exc}") from exc
    if not resp.ok or not data.get("status"):
        raise PaystackError(data.get("message", "Could not create payout subaccount."))
    return data["data"]
 
 
def _paystack_update_subaccount(subaccount_code, **fields):
    try:
        resp = requests.put(
            f"{PAYSTACK_BASE_URL}/subaccount/{subaccount_code}",
            json=fields,
            headers=_paystack_headers(),
            timeout=15,
        )
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise PaystackError(f"Could not reach Paystack: {exc}") from exc
    if not resp.ok or not data.get("status"):
        raise PaystackError(data.get("message", "Could not update payout subaccount."))
    return data["data"]
 
 
 
def guess_momo_network(phone_number):
    """
    Best-effort network guess from a Ghanaian phone number's prefix.
    """
    digits = "".join(ch for ch in str(phone_number) if ch.isdigit())
    if digits.startswith("233"):
        digits = "0" + digits[3:]
    elif not digits.startswith("0"):
        digits = "0" + digits
    return GHANA_MOMO_PREFIXES.get(digits[:3])
 
 
def _bank_code_for_network(network_label):
    """
    Matches a guessed/chosen network name ('MTN', 'Telecel', 'AirtelTigo')
    against Paystack's live GET /bank?type=mobile_money list by substring,
    """
    options = list_ghana_momo_networks()
    match = next((o for o in options if network_label.lower() in o["name"].lower()), None)
    if not match:
        raise PaystackError(f"Couldn't find '{network_label}' in Paystack's Ghana MoMo network list.")
    return match["code"], match["name"]
 

def resolve_account_number(account_number, bank_code):
    """
    GET /bank/resolve — confirms an account number/bank_code pair
    actually belongs to someone, and returns their name, BEFORE any
    subaccount is created.
    """
    try:
        resp = requests.get(
            f"{PAYSTACK_BASE_URL}/bank/resolve",
            params={"account_number": account_number, "bank_code": bank_code},
            headers=_paystack_headers(),
            timeout=15,
        )
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise PaystackError(f"Could not reach Paystack: {exc}") from exc
    if not resp.ok or not data.get("status"):
        raise PaystackError(
            data.get("message", "Could not verify that account — check the number and try again.")
        )
    return data["data"]  # {"account_number", "account_name", "bank_id"}
 

def save_landlord_payout_account(landlord, bank_code, bank_name, account_number, account_name):
    """
    Always Mobile Money. Creates the Paystack subaccount on first save;
    updates the SAME subaccount via PUT on any later change — the
    OneToOne on the model means one landlord, one subaccount_code, ever.
    """
    percentage_charge = getattr(settings, "PLATFORM_FEE_PERCENTAGE", Decimal("0.0"))
 
    account, created = LandlordPayoutAccount.objects.get_or_create(
        landlord=landlord,
        defaults=dict(
            bank_code=bank_code,
            bank_name=bank_name,
            account_number=account_number,
            account_name=account_name,
            percentage_charge=percentage_charge,
        ),
    )
 
    if created:
        data = _paystack_create_subaccount(
            business_name=account_name,
            settlement_bank=bank_code,
            account_number=account_number,
            percentage_charge=float(percentage_charge),
        )
        account.paystack_subaccount_code = data["subaccount_code"]
    else:
        account.bank_code = bank_code
        account.bank_name = bank_name
        account.account_number = account_number
        account.account_name = account_name
        _paystack_update_subaccount(
            account.paystack_subaccount_code,
            settlement_bank=bank_code,
            account_number=account_number,
        )
 
    account.verified_at = timezone.now()
    account.save()
    return account
 

def ensure_landlord_payout_account(landlord):
    """
    Silent, automatic payout setup — no page visit, no click, in the
    common case. This replaces the old "landlord must go visit a setup
    page" flow per your call: the safety check (Paystack confirming the
    guessed number+network resolves to a real name) still happens, it
    just happens invisibly in the background instead of gating on a
    human looking at a confirm screen first.
 
    Returns the LandlordPayoutAccount if one now exists and is ready
    (whether it already did, or was just silently created). Returns
    None if it genuinely can't be resolved automatically — landlord's
    number doesn't match a recognized network, or Paystack couldn't
    verify it (e.g. the registered number isn't actually MoMo-registered
    at all). A None here is the ONLY case that should surface anything
    to the landlord — everything else stays invisible.
 
    Deliberately swallows PaystackError rather than raising — this gets
    called from places (like tenancies._execute_agreement()) that
    shouldn't fail just because Paystack is briefly unreachable; a
    payout account can always be resolved later, either automatically
    on the next call or via the manual fallback.
 
    Note: if a landlord's number genuinely can't auto-resolve, this
    re-attempts the same failing lookup every time it's called (e.g.
    every initiate_payment()) rather than caching the failure — fine at
    this scale, but worth a TTL/backoff if Paystack call volume ever
    becomes a real cost.
    """
    existing = getattr(landlord, "payout_account", None)
    if existing and existing.is_ready and not existing.is_stale:
        return existing
 
    phone_number = landlord.phone_number
    network = guess_momo_network(phone_number)
    if not network:
        return None  # ambiguous/unrecognized prefix — needs a human to pick
 
    try:
        bank_code, bank_name = _bank_code_for_network(network)
        resolved = resolve_account_number(phone_number, bank_code)
        return save_landlord_payout_account(
            landlord=landlord,
            bank_code=bank_code,
            bank_name=bank_name,
            account_number=phone_number,
            account_name=resolved["account_name"],
        )
    except PaystackError:
        return None  # wrong network guess, Paystack down, or unresolvable — needs a human

def _paystack_verify_transaction(reference):
    """GET /transaction/verify/:reference."""
    try:
        resp = requests.get(
            f"{PAYSTACK_BASE_URL}/transaction/verify/{reference}",
            headers=_paystack_headers(),
            timeout=15,
        )
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise PaystackError(f"Could not reach Paystack: {exc}") from exc

    if not resp.ok or not data.get("status"):
        raise PaystackError(data.get("message", "Paystack verify failed."))

    return data["data"]


def verify_webhook_signature(request_body, signature_header):
    """
    Paystack signs webhook payloads with HMAC-SHA512 of the raw request
    body, using the secret key, sent in the X-Paystack-Signature header.
    hmac.compare_digest, not `==` — a plain equality check on a security
    comparison is a timing side-channel.
    """
    secret = _paystack_secret_key()
    computed = hmac.new(secret.encode("utf-8"), request_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(computed, signature_header or "")


def get_accepted_schedule(tenancy):
    """
    Returns the instalment_schedule list from the ACCEPTED Proposal for
    this tenancy, or [] if none. Reuses documents.services'
    _get_accepted_proposal() rather than re-implementing the same
    `tenancy.proposals.filter(status=ACCEPTED).first()` lookup a third
    time — see handoff v12 for the note on making that helper public.
    """
    proposal = _get_accepted_proposal(tenancy)
    return proposal.instalment_schedule if proposal else []


def _as_date(value):
    return date.fromisoformat(value) if isinstance(value, str) else value


def get_instalment_schedule_with_status(tenancy):
    """
    Merges the accepted Proposal's instalment_schedule with actual
    Payment records, matched by due_date, so a landlord/tenant view can
    show paid/due/overdue per scheduled instalment without the template
    doing its own date arithmetic.
    """
    schedule = get_accepted_schedule(tenancy)
    successful = {
        p.instalment_due_date: p
        for p in tenancy.payments.filter(
            payment_type=PaymentType.INSTALMENT, status=PaymentStatus.SUCCESS
        )
    }
    today = date.today()
    rows = []
    for entry in schedule:
        due_date = _as_date(entry["due_date"])
        payment = successful.get(due_date)
        if payment:
            row_status = "paid"
        elif due_date < today:
            row_status = "overdue"
        else:
            row_status = "due"
        rows.append({**entry, "due_date": due_date, "status": row_status, "payment": payment})
    return rows


def get_overdue_instalments(tenancy):
    return [row for row in get_instalment_schedule_with_status(tenancy) if row["status"] == "overdue"]


def check_overdue_instalments():
    """
    Meant to run daily (Month 3: Celery beat task, per v7 §17 — "Celery
    tasks for instalment reminders"). No Celery task/schedule is wired
    up this session — this is the plain function such a task would
    call, and it's also callable today from a manual management command
    (not written yet) or the Django shell. Returns overdue rows across
    every ACTIVE tenancy, grouped by tenancy, for a landlord dashboard
    alert.

    generate_default_notice() (v7 §17, marked "optional") is
    deliberately NOT implemented — a default/eviction notice is a much
    heavier legal document than a receipt and needs product + legal
    input on trigger conditions (how many days overdue, what it legally
    has to say) before it's worth building. Flagging, not guessing.
    """
    from apps.tenancies.models import Tenancy, TenancyStatus

    results = []
    for tenancy in Tenancy.objects.filter(status=TenancyStatus.ACTIVE):
        overdue = get_overdue_instalments(tenancy)
        if overdue:
            results.append({"tenancy": tenancy, "overdue": overdue})
    return results



def get_instalments_due_soon(tenancy, days_ahead=3):
    """
    Instalments due within the next `days_ahead` days, inclusive of
    today — not yet overdue. A range, not an exact-day match: since this
    runs daily, the same instalment shows up here on each day of the
    countdown, giving a real daily reminder rather than one one-off ping.
    """
    today = date.today()
    return [
        row
        for row in get_instalment_schedule_with_status(tenancy)
        if row["status"] == "due" and 0 <= (row["due_date"] - today).days <= days_ahead
    ]
 
 
def get_recently_overdue_instalments(tenancy, grace_days=3):
    """
    Instalments overdue by 1 to `grace_days` days — the daily-reminder
    window before automated chasing stops. 
    """
    today = date.today()
    return [
        row
        for row in get_instalment_schedule_with_status(tenancy)
        if row["status"] == "overdue" and 1 <= (today - row["due_date"]).days <= grace_days
    ]
 
 
def get_reminder_grace_expired_instalments(tenancy, grace_days=3):
    """
    Instalments that just crossed out of the grace_days reminder window
    — overdue by exactly grace_days + 1 days. This is the one specific
    day the landlord gets an explicit "automated reminders have ended,
    this is yours now" notice, rather than the app just going silent
    with no signal that it's stopped chasing this instalment.
    """
    today = date.today()
    return [
        row
        for row in get_instalment_schedule_with_status(tenancy)
        if row["status"] == "overdue" and (today - row["due_date"]).days == grace_days + 1
    ]
 
 
def send_instalment_reminders(days_ahead=3, grace_days=3):
    """
    The function apps/payments/management/commands/send_payment_reminders.py
    calls. Walks every ACTIVE tenancy once, sends:
      - a daily "due soon" SMS to the tenant, starting `days_ahead` days
        before each instalment's due date, through the due date itself
      - a daily "overdue" SMS to both tenant and landlord, for the first
        `grace_days` days after an instalment's due date passes unpaid
      - a one-time handoff SMS to the landlord only, the day after the
        grace window expires, then nothing further for that instalment
 
    Returns counts for the management command to report on stdout.
    """
    from apps.tenancies.models import Tenancy, TenancyStatus
 
    today = date.today()
    due_soon_sent = 0
    overdue_sent = 0
    handoff_sent = 0
 
    for tenancy in Tenancy.objects.filter(status=TenancyStatus.ACTIVE):
        for row in get_instalments_due_soon(tenancy, days_ahead=days_ahead):
            days_left = (row["due_date"] - today).days
            when_text = (
                "today" if days_left == 0
                else f"in {days_left} day{'s' if days_left != 1 else ''} ({row['due_date']})"
            )
            notify_user(
                tenancy.tenant,
                f"Reminder: your rent instalment of GHS {row['amount']} for "
                f"{tenancy.rental_property.title} is due {when_text}.",
                purpose=NotificationPurpose.PAYMENT,
            )
            due_soon_sent += 1
 
        for row in get_recently_overdue_instalments(tenancy, grace_days=grace_days):
            days_overdue = (today - row["due_date"]).days
            notify_user(
                tenancy.tenant,
                f"Your rent instalment of GHS {row['amount']} for "
                f"{tenancy.rental_property.title} was due on {row['due_date']} "
                f"and is now {days_overdue} day{'s' if days_overdue != 1 else ''} "
                f"overdue. Please make payment as soon as possible.",
                purpose=NotificationPurpose.PAYMENT,
            )
            notify_user(
                tenancy.landlord,
                f"Your tenant's({tenancy.tenant.get_full_name()}) instalment of GHS {row['amount']} for "
                f"{tenancy.rental_property.title} (due {row['due_date']}) is "
                f"now {days_overdue} day{'s' if days_overdue != 1 else ''} overdue.",
                purpose=NotificationPurpose.PAYMENT,
            )
            overdue_sent += 1
 
        for row in get_reminder_grace_expired_instalments(tenancy, grace_days=grace_days):
            notify_user(
                tenancy.landlord,
                f"Your tenant's instalment of GHS {row['amount']} for "
                f"{tenancy.rental_property.title} (due {row['due_date']}) is now "
                f"{grace_days + 1} days overdue. Automated reminders have ended "
                f"— please follow up directly.",
                purpose=NotificationPurpose.PAYMENT,
            )
            handoff_sent += 1
 
    return {
        "due_soon_sent": due_soon_sent,
        "overdue_sent": overdue_sent,
        "handoff_sent": handoff_sent,
    }
 


def initiate_payment(tenancy, payer, payment_type, callback_url, instalment_due_date=None):
    """
    Creates a PENDING Payment row and calls Paystack's initialize
    endpoint. Returns (payment, authorization_url) — the view redirects
    the payer's browser to authorization_url.

    Guards:
      - payer is the tenant on this tenancy (landlords don't pay)
      - MOVE_IN: tenancy must be PENDING_PAYMENT; no existing SUCCESS
        move-in payment already recorded (no double-charging on a
        retried/duplicate click)
      - INSTALMENT: tenancy must be ACTIVE (an instalment on a tenancy
        that never went active makes no sense — move-in comes first);
        instalment_due_date must match an entry in the accepted
        Proposal's schedule; that entry must not already have a SUCCESS
        payment against it

    The Payment row is created and saved BEFORE the Paystack call, and
    deliberately not inside the same atomic block as that network call
    — the row needs to durably exist (status=PENDING) even if Paystack
    is unreachable, so there's a record of the attempt. If the Paystack
    call then fails, this marks that same row FAILED and re-raises,
    rather than leaving it silently PENDING forever.
    """
    if payer != tenancy.tenant:
        raise ValueError("Only the tenant on this tenancy can make a payment.")

    from apps.tenancies.models import TenancyStatus

    if payment_type == PaymentType.MOVE_IN:
        if tenancy.status != TenancyStatus.PENDING_PAYMENT:
            raise ValueError(
                "Move-in payment can only be made while the tenancy is "
                f"awaiting payment. This tenancy is '{tenancy.get_status_display()}'."
            )
        if tenancy.payments.filter(
            payment_type=PaymentType.MOVE_IN, status=PaymentStatus.SUCCESS
        ).exists():
            raise ValueError("Move-in payment has already been completed for this tenancy.")

        amount = _financial_display_context(tenancy)["display_advance_amount"]
        due_date = None

    elif payment_type == PaymentType.INSTALMENT:
        if tenancy.status != TenancyStatus.ACTIVE:
            raise ValueError(
                "Instalment payments can only be made once the tenancy is "
                f"active. This tenancy is '{tenancy.get_status_display()}'."
            )
        if instalment_due_date is None:
            raise ValueError("instalment_due_date is required for instalment payments.")

        due_date = _as_date(instalment_due_date)
        schedule = get_accepted_schedule(tenancy)
        match = next((e for e in schedule if str(e["due_date"]) == str(instalment_due_date)), None)
        if match is None:
            raise ValueError("No scheduled instalment matches that due date.")

        if tenancy.payments.filter(
            payment_type=PaymentType.INSTALMENT,
            instalment_due_date=due_date,
            status=PaymentStatus.SUCCESS,
        ).exists():
            raise ValueError("This instalment has already been paid.")

        amount = match["amount"]

    else:
        raise ValueError(f"Unknown payment_type: {payment_type}")

    reference = f"rrgh-{uuid.uuid4().hex}"
    with transaction.atomic():
        payment = Payment.objects.create(
            tenancy=tenancy,
            paid_by=payer,
            payment_type=payment_type,
            amount=amount,
            instalment_due_date=due_date,
            reference=reference,
        )
        tenancy.status = TenancyStatus.ACTIVE
        tenancy.save(update_fields=["status", "updated_at"])

    try:
        paystack_data = _paystack_initialize_transaction(
            email=payer.email,
            amount=amount,
            reference=reference,
            callback_url=callback_url,
        )
    except PaystackError:
        payment.status = PaymentStatus.FAILED
        payment.save(update_fields=["status", "updated_at"])
        raise

    return payment, paystack_data["authorization_url"]


def verify_and_record_payment(reference):
    """
    Source of truth for "did this payment actually succeed." Called
    from both the webhook (server-to-server, authoritative) and the
    browser callback (UX only — the payer's redirect back from
    Paystack) — always re-verifies against Paystack's own
    /transaction/verify endpoint rather than trusting whatever the
    webhook payload or callback query string claims, per Paystack's own
    integration guidance. A hand-edited callback URL can't fake a
    successful payment this way.

    Idempotent: if this Payment is already SUCCESS, returns it unchanged
    without re-running side effects — both the webhook and the callback
    can legitimately call this for the same reference, and activation /
    receipt generation must only happen once.
    """
    try:
        payment = Payment.objects.select_related("tenancy").get(reference=reference)
    except Payment.DoesNotExist:
        raise ValueError(f"No payment found for reference '{reference}'.")

    if payment.status == PaymentStatus.SUCCESS:
        return payment

    data = _paystack_verify_transaction(reference)
    paystack_status = data.get("status")  # 'success' / 'failed' / 'abandoned' / ...

    with transaction.atomic():
        payment.gateway_response = data
        payment.paystack_transaction_id = str(data.get("id", ""))
        payment.channel = data.get("channel", "")

        if paystack_status == "success":
            payment.status = PaymentStatus.SUCCESS
            paid_at = data.get("paid_at")
            payment.paid_at = parse_datetime(paid_at) if paid_at else timezone.now()
            payment.save()
            _on_payment_success(payment)
        else:
            payment.status = (
                PaymentStatus.ABANDONED if paystack_status == "abandoned" else PaymentStatus.FAILED
            )
            payment.save()

    return payment


def _on_payment_success(payment):
    """
    Side effects once a payment is confirmed successful:
      - MOVE_IN: activates the tenancy — this is the "Paystack webhook
        → activate_tenancy()" link from v7 §17, replacing the manual
        landlord button. tenancy.landlord is passed straight through;
        activate_tenancy()'s "landlord owns the property" guard is
        trivially satisfied since that's exactly where it came from —
        same "no delegation model exists yet" caveat noted in the
        listings handoff (v11 §5.2).
      - Both types: generates a Payment Receipt PDF (Act 220 §33) into
        the documents vault.
      - SMS: stubbed, same pattern as everywhere else pending the
        notifications app (Month 3) — see _notify() below.
    """
    from apps.documents.services import generate_payment_receipt
    from apps.tenancies.services import activate_tenancy

    tenancy = payment.tenancy

    if payment.payment_type == PaymentType.MOVE_IN:
        activate_tenancy(tenancy, landlord=tenancy.landlord)

    generate_payment_receipt(payment)
    generate_rent_card(tenancy)

    notify_user(
        tenancy.tenant,
        f"Payment of GHS {payment.amount} received. Your receipt is ready.",
        purpose=NotificationPurpose.PAYMENT
    )
    notify_user(
        tenancy.landlord,
        f"Payment of GHS {payment.amount} received from your tenant for "
        f"{tenancy.rental_property.title}.",
        purpose=NotificationPurpose.PAYMENT
    )

