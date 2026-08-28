"""
All tenancy and agreement state transitions live here. All raise
ValueError with a user-facing message on guard failures. Views catch
ValueError and decide the HTTP semantics.

  - create_tenancy() opens a tenancy in PENDING_NEGOTIATION, 
    No Agreement and no PDFs are created at this point.
  - Agreement lifecycle: formalise_special_conditions(),
    save_special_conditions(), confirm_agreement_landlord(),
    confirm_agreement_tenant(), _execute_agreement().
"""

from django.db import transaction
from django.utils import timezone

from dateutil.relativedelta import relativedelta

from apps.listings.models import ListingStatus



def create_tenancy(application, landlord):
    """
    Create a Tenancy from an APPROVED Application.

    Opens the tenancy in PENDING_NEGOTIATION. The bilateral instalment
    negotiation engine (negotiations app — not yet built) takes it from
    there: once a proposal is accepted, negotiations.accept_proposal()
    is responsible for creating the Agreement and moving the tenancy to
    PENDING_AGREEMENT. No Agreement and no documents are
    created here.

    Side effects (all inside one atomic block):
      - Tenancy row created (status=PENDING_NEGOTIATION)
      - rental_property.status locked (no further applications)
      - All other PENDING applications for the same property → DECLINED

    Guards (in order):
      1. landlord owns the property
      2. application is APPROVED
      3. no Tenancy already exists for this application
    """
    from apps.applications.models import ApplicationStatus

    prop = application.rental_property

    if prop.landlord != landlord:
        raise ValueError("You do not own this property.")

    if application.status != ApplicationStatus.APPROVED:
        raise ValueError(
            "A tenancy can only be created from an approved application. "
            f"This application is '{application.get_status_display()}'."
        )

    # Guard against duplicate — OneToOneField will also enforce at DB level,
    if hasattr(application, "tenancy"):
        raise ValueError("A tenancy already exists for this application.")

    # Freeze financial terms from the property at this exact moment.
    monthly_rent   = prop.monthly_rent
    advance_months = prop.advance_months
    advance_amount = monthly_rent * advance_months

    start_date = application.move_in_date
    end_date   = start_date + relativedelta(months=prop.lease_term_months)

    with transaction.atomic():
        from apps.tenancies.models import Tenancy, TenancyStatus

        tenancy = Tenancy.objects.create(
            application     = application,
            rental_property = prop,
            landlord        = landlord,
            tenant          = application.tenant,
            status          = TenancyStatus.PENDING_NEGOTIATION,
            monthly_rent    = monthly_rent,
            advance_months  = advance_months,
            advance_amount  = advance_amount,
            start_date      = start_date,
            end_date        = end_date,
        )

        # Lock the property — no further applications can be submitted.
        prop.status = ListingStatus.PENDING_PAYMENT
        prop.save(update_fields=["status", "updated_at"])

        #decline all other PENDING applications for this property.
        _decline_remaining_applications(prop, exclude_application=application)

        #opens negotiation, prefilled with the property's default instalment terms.
        from apps.negotiations.services import open_negotiation
        open_negotiation(tenancy)

    return tenancy


def activate_tenancy(tenancy, landlord):
    """
    Transition a tenancy from PENDING_PAYMENT → ACTIVE.
    Called after advance payment is confirmed .
    
    Guards:
      1. landlord owns the property
      2. tenancy is in PENDING_PAYMENT state
    """
    from apps.tenancies.models import TenancyStatus

    if tenancy.rental_property.landlord != landlord:
        raise ValueError("You do not own this property.")

    if tenancy.status != TenancyStatus.PENDING_PAYMENT:
        raise ValueError(
            "Only tenancies awaiting payment can be activated. "
            f"This tenancy is '{tenancy.get_status_display()}'."
        )

    tenancy.status = TenancyStatus.ACTIVE
    tenancy.save(update_fields=["status", "updated_at"])
    tenancy.rental_property.status = ListingStatus.RENTED
    tenancy.rental_property.save(update_fields=["status"])

    return tenancy



def formalise_special_conditions(raw_text):
    """
    Send the landlord's plain-language special conditions to Claude
    (model: claude-sonnet-4-6) for legal formalisation into clean clause
    text suitable for a tenancy agreement.

    Never raises — on any API error (missing key, network failure, rate
    limit) this falls back to returning the raw text unchanged, per the
    handoff's "Claude API — special conditions formaliser" gotcha:
    handle API errors gracefully, fall back to raw text if unavailable.
    Store raw input AND formalised output separately; the landlord always
    gets a review step before anything is committed
    """
    from django.conf import settings

    if not raw_text or not raw_text.strip():
        return ""

    try:
        import anthropic

        api_key = getattr(settings, "ANTHROPIC_API_KEY", None)
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            system=(
                "You are a legal drafting assistant formalising tenancy "
                "special conditions under Ghana's Rent Act, 1963 (Act "
                "220). Rewrite the landlord's plain-language input as a "
                "clear, formal clause suitable for a tenancy agreement. "
                "Do not invent terms absent from the input. Do not "
                "contradict Act 220 (e.g. never imply advance rent may "
                "exceed six months). Return only the formalised clause "
                "text — no preamble, no commentary."
            ),
            messages=[{"role": "user", "content": raw_text}],
        )
        formalised = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        ).strip()
        return formalised or raw_text
    except Exception:
        # API unavailable, misconfigured, or rate-limited — never block
        # the landlord's workflow.
        return raw_text


def save_special_conditions(agreement, raw_text, formalised_text):
    """
    Persist both the raw landlord input and the Claude-formalised output
    on the Agreement. Called only after the landlord has reviewed the
    formalised text in the UI — never auto-committed straight from
    formalise_special_conditions().
    """
    agreement.special_conditions_raw = raw_text
    agreement.special_conditions = formalised_text
    agreement.save(
        update_fields=["special_conditions_raw", "special_conditions", "updated_at"]
    )
    return agreement


# Agreement — dual OTP confirmation
def confirm_agreement_landlord(agreement, landlord, otp_code):
    """
    Landlord confirms the tenancy agreement via OTP (purpose='tenancy_confirm').

    Guards:
      1. landlord is the landlord party on this tenancy
      2. agreement is not already fully executed
      3. OTP is valid

    If the tenant has already confirmed, this triggers full execution
    (_execute_agreement). Otherwise the agreement moves to PENDING_TENANT.
    """
    from apps.accounts.services import verify_otp
    from apps.tenancies.models import AgreementStatus

    if landlord != agreement.tenancy.landlord:
        raise ValueError("You are not the landlord on this tenancy.")

    if agreement.status == AgreementStatus.FULLY_EXECUTED:
        raise ValueError("This agreement has already been fully executed.")

    otp_ref = verify_otp(landlord, otp_code, purpose="tenancy_confirm")
    if not otp_ref:
        raise ValueError("Invalid or expired OTP.")

    agreement.landlord_confirmed_at = timezone.now()
    agreement.landlord_otp_ref = otp_ref

    if agreement.tenant_confirmed_at:
        agreement.save(
            update_fields=["landlord_confirmed_at", "landlord_otp_ref", "updated_at"]
        )
        _execute_agreement(agreement)
    else:
        agreement.status = AgreementStatus.PENDING_TENANT
        agreement.save(
            update_fields=[
                "landlord_confirmed_at",
                "landlord_otp_ref",
                "status",
                "updated_at",
            ]
        )

    return agreement


def confirm_agreement_tenant(agreement, tenant, otp_code):
    """
    Tenant confirms the tenancy agreement via OTP. Mirror of
    confirm_agreement_landlord — see that docstring for the shared logic.

    If the landlord hasn't confirmed yet (tenant acting first — not the
    normal path, but handled gracefully), status is set to
    PENDING_LANDLORD rather than left inconsistent.
    """
    from apps.accounts.services import verify_otp
    from apps.tenancies.models import AgreementStatus

    if tenant != agreement.tenancy.tenant:
        raise ValueError("You are not the tenant on this tenancy.")

    if agreement.status == AgreementStatus.FULLY_EXECUTED:
        raise ValueError("This agreement has already been fully executed.")

    otp_ref = verify_otp(tenant, otp_code, purpose="tenancy_confirm")
    if not otp_ref:
        raise ValueError("Invalid or expired OTP")

    agreement.tenant_confirmed_at = timezone.now()
    agreement.tenant_otp_ref = otp_ref

    if agreement.landlord_confirmed_at:
        agreement.save(
            update_fields=["tenant_confirmed_at", "tenant_otp_ref", "updated_at"]
        )
        _execute_agreement(agreement)
    else:
        agreement.status = AgreementStatus.PENDING_LANDLORD
        agreement.save(
            update_fields=[
                "tenant_confirmed_at",
                "tenant_otp_ref",
                "status",
                "updated_at",
            ]
        )

    return agreement


def _execute_agreement(agreement):
    """
    Called once BOTH parties have confirmed via OTP. Fully executes the
    agreement, advances the tenancy to PENDING_PAYMENT, and generates
    the Tenancy Agreement + Rent Card PDFs.

    apps.documents.services.generate_tenancy_agreement() and
    generate_rent_card() are called here, inside the same atomic block,
    so a failure generating either PDF rolls back the FULLY_EXECUTED /
    PENDING_PAYMENT transition rather than leaving the agreement
    executed with no documents. If PDF generation needs to be
    best-effort instead (i.e. execution should succeed even if
    WeasyPrint errors), move the generate_* calls outside the
    transaction.atomic() block — that's a product decision, not
    something to silently assume either way.

    TODO (notifications app, Month 3): SMS both parties — currently a
    stub, per handoff §19 (`_notify(user, message)`).
    """
    from apps.documents.services import generate_rent_card, generate_tenancy_agreement, generate_instalment_addendum
    from apps.tenancies.models import AgreementStatus, TenancyStatus
    from apps.negotiations.models import ProposalStatus

    with transaction.atomic():
        agreement.status = AgreementStatus.FULLY_EXECUTED
        agreement.fully_executed_at = timezone.now()
        agreement.save(update_fields=["status", "fully_executed_at", "updated_at"])

        tenancy = agreement.tenancy
        tenancy.status = TenancyStatus.PENDING_PAYMENT
        tenancy.save(update_fields=["status", "updated_at"])

        generate_tenancy_agreement(agreement)
        generate_instalment_addendum(agreement)

    try:
        from apps.payments.services import ensure_landlord_payout_account
        ensure_landlord_payout_account(tenancy.landlord)
    except Exception:
        pass

    return agreement




def _decline_remaining_applications(rental_property, exclude_application):
    """
    Decline all PENDING applications for rental_property except the one
    that just became a tenancy.

    Called inside create_tenancy's atomic block.
    """
    from apps.applications.models import Application, ApplicationStatus

    Application.objects.filter(
        rental_property=rental_property,
        status=ApplicationStatus.PENDING,
    ).exclude(
        pk=exclude_application.pk,
    ).update(status=ApplicationStatus.DECLINED)
