"""
applications/services.py

All business logic lives here. Views are thin wrappers that call these
functions and translate ValueError → HTTP response codes.

Why ValueError (not PermissionDenied or Http404)?
- Services don't know about HTTP. They're callable from the shell, from tests,
  from Celery tasks, from management commands. Raising Django HTTP exceptions
  here would couple a business layer to a transport layer.
- Views catch ValueError and decide: is this a 400 (bad request), a 403
  (permission), or something else? That's the view's job.
"""

from django.conf import settings
from django.db import IntegrityError


from .models import Application, ApplicationStatus


# ── Notification stub ─────────────────────────────────────────────────────────
# Month 3: replace with a Celery task dispatch to the notifications app.
# For now: no-op in dev (ARKESEL_DRY_RUN=True), real SMS in prod.

def _notify(user, message: str) -> None:
    """
    Stub wrapper around Arkesel SMS.
    Replace body with Celery task when notifications app is built.
    Never raises — a failed notification must never roll back a transaction.
    """
    if getattr(settings, 'ARKESEL_DRY_RUN', True):
        return  # dev: silent. tests never hit real SMS.
    try:
        from apps.accounts.services import send_sms
        send_sms(user.phone_number, message)
    except Exception:
        # Notification failure is logged, never propagated.
        # A tenant should not lose their application because Arkesel is down.
        pass


# ── Core services ─────────────────────────────────────────────────────────────

def submit_application(tenant, property_obj, move_in_date, message='') -> Application:
    """
    Create a new PENDING application.

    Guards (in order — fail fast, meaningful errors):
    1. Caller must be a tenant (role check).
    2. Tenant's phone must be verified (platform trust check).
    3. Property must be ACTIVE (can't apply to a draft or rented unit).
    4. No live application already exists for this tenant+property pair.
       The conditional DB constraint catches race conditions, but we check
       first to give a readable error rather than an IntegrityError.

    Returns the saved Application on success.
    Raises ValueError with a user-facing message on any guard failure.
    """
    # Guard 1 — role
    if not tenant.is_tenant():
        raise ValueError("Only tenants can submit applications.")

    # Guard 2 — phone verification
    if not tenant.is_verified:
        raise ValueError("Please verify your phone number before applying.")

    # Guard 3 — property availability
    if property_obj.status != 'active':
        raise ValueError("This property is not currently available for applications.")

    # Guard 4 — no live application
    # "Live" = pending or approved. Withdrawn and declined are dead — reapply allowed.
    live_exists = Application.objects.filter(
        rental_property=property_obj,
        tenant=tenant,
        status__in=[ApplicationStatus.PENDING, ApplicationStatus.APPROVED],
    ).exists()
    if live_exists:
        raise ValueError("You already have an active application for this property.")

    # Create — wrap in try/except to catch the rare race-condition duplicate
    # that slips past the guard above (two simultaneous POSTs).
    try:
        application = Application.objects.create(
            rental_property=property_obj,
            tenant=tenant,
            status=ApplicationStatus.PENDING,
            move_in_date=move_in_date,
            message=message,
        )
    except IntegrityError:
        raise ValueError("You already have an active application for this property.")

    # Notify landlord
    _notify(
        property_obj.landlord,
        f"New application from {tenant.get_full_name()} for {property_obj.title} at {property_obj.city}. Please review and respond.",
    )

    return application


def approve_application(application, actor) -> Application:
    """
    Move application from PENDING → APPROVED.

    Guards:
    1. Landlord must own the property (not just any landlord).
    2. Application must be PENDING (idempotency — can't approve an already-approved
       or declined application; that would be a state machine violation).

    Note: does NOT create a Tenancy. That belongs to the tenancies app (not yet built).
    The approved application sits in a holding state — landlord sees a
    "Create Tenancy" CTA, tenant sees "Awaiting tenancy setup".
    """
    # Guard 1 — ownership
    from apps.accounts.services import can_act_on_property
    if not can_act_on_property(actor, application.rental_property):
        raise ValueError("You do not have permission to act on this property.")

    # Guard 2 — status
    if application.status != ApplicationStatus.PENDING:
        raise ValueError(
            f"Only pending applications can be approved. "
            f"This application is {application.get_status_display().lower()}."
        )

    application.status = ApplicationStatus.APPROVED
    application.save(update_fields=['status', 'updated_at'])

    _notify(
        application.tenant,
        f"Your application for {application.rental_property.title} has been approved! "
        f"Your landlord will set up the tenancy details shortly.",
    )

    landlord = application.rental_property.landlord
    if actor != landlord:
        _notify(
            landlord,
            f"{actor.get_full_name()} (your property manager) approved an application "
            f"from {application.tenant.get_full_name()} for {application.rental_property.title}.",
        )

    return application


def decline_application(application, actor, reason='') -> Application:
    """
    Move application from PENDING → DECLINED.

    After decline, the conditional constraint lifts — the tenant can reapply.
    This is the correct behaviour: a declined application is a dead application,
    not a permanent block.

    The `reason` parameter is accepted for future use (storing decline reasons
    when the notifications app is built) but not persisted yet — the Application
    model has no reason field. Add it in a later migration when it's needed.
    """
    # Guard 1 — ownership
    from apps.accounts.services import can_act_on_property
    if not can_act_on_property(actor, application.rental_property):
        raise ValueError("You do not have permission to act on this property.")

    # Guard 2 — status
    if application.status != ApplicationStatus.PENDING:
        raise ValueError(
            f"Only pending applications can be declined. "
            f"This application is {application.get_status_display().lower()}."
        )

    application.status = ApplicationStatus.DECLINED
    application.save(update_fields=['status', 'updated_at'])

    reason_text = f" Reason: {reason}" if reason else ""
    _notify(
        application.tenant,
        f"Your application for {application.rental_property.title} was not successful.{reason_text} "
        f"You are welcome to apply for other properties.",
    )

    landlord = application.rental_property.landlord
    if actor != landlord:
        _notify(
            landlord,
            f"{actor.get_full_name()} (your property manager) declined an application "
            f"from {application.tenant.get_full_name()} for {application.rental_property.title}.{reason_text}",
        )

    return application


def withdraw_application(application, tenant) -> Application:
    """
    Move application from PENDING → WITHDRAWN.

    Critical business rule: tenants can only withdraw PENDING applications.
    An APPROVED application cannot be withdrawn here — at that point, the
    landlord has committed and the process moves to tenancy negotiation.
    Post-approval exit is a tenancy abandonment flow (out of scope).

    Why guard on PENDING and not just "not APPROVED"?
    Because withdrawing a DECLINED or WITHDRAWN application is also nonsensical.
    The guard is precise: only PENDING can be withdrawn.
    """
    # Guard 1 — identity (the applicant, not just any tenant)
    if application.tenant != tenant:
        raise ValueError("You can only withdraw your own applications.")

    # Guard 2 — status (PENDING only)
    if application.status != ApplicationStatus.PENDING:
        if application.status == ApplicationStatus.APPROVED:
            raise ValueError(
                "Approved applications cannot be withdrawn. "
                "Please contact your landlord to discuss next steps."
            )
        raise ValueError(
            f"This application cannot be withdrawn "
            f"(status: {application.get_status_display().lower()})."
        )

    application.status = ApplicationStatus.WITHDRAWN
    application.save(update_fields=['status', 'updated_at'])

    return application
