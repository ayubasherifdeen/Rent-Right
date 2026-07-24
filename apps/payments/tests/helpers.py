"""
ASSUMPTION FLAGGED, WHOLE FILE: I don't have accounts/models.py,
listings/models.py, or applications/models.py this session, so the
User/Property/Application field names below (email, phone_number,
title, monthly_rent, advance_months, lease_term_months, move_in_date,
etc.) are inferred from how they're referenced elsewhere in the
tenancies/negotiations/documents code you've shared, not confirmed
against the real model definitions. This file has NOT been run against
your actual project this session (no Paystack account either — see
handoff v12). Treat test_services.py + this file as a draft to run and
fix up against real errors, the same way tenancies' test suite was
iterated in three real passes in handoff v8 §2.10 — not as
already-verified passing tests.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model

from apps.applications.models import Application, ApplicationStatus
from apps.listings.models import ListingStatus, Property
from apps.negotiations.models import Proposal, ProposalStatus
from apps.tenancies.models import Tenancy, TenancyStatus

User = get_user_model()


def make_user(email, **extra):
    defaults = {"email": email, "phone_number": f"+233{abs(hash(email)) % 10**9:09d}"}
    defaults.update(extra)
    user = User(**defaults)
    user.set_password("testpass123")
    user.save()
    return user


def make_property(landlord, **extra):
    defaults = dict(
        landlord=landlord,
        title="Test Property",
        monthly_rent=Decimal("1500.00"),
        advance_months=3,
        lease_term_months=12,
        status=ListingStatus.PENDING_PAYMENT,
    )
    defaults.update(extra)
    return Property.objects.create(**defaults)


def make_application(tenant, rental_property, **extra):
    defaults = dict(
        tenant=tenant,
        rental_property=rental_property,
        status=ApplicationStatus.APPROVED,
        move_in_date=date.today() + timedelta(days=14),
    )
    defaults.update(extra)
    return Application.objects.create(**defaults)


def make_pending_payment_tenancy():
    """Tenancy sitting in PENDING_PAYMENT, ready for a move-in payment test."""
    landlord = make_user("landlord@test.com")
    tenant = make_user("tenant@test.com")
    prop = make_property(landlord)
    application = make_application(tenant, prop)

    return Tenancy.objects.create(
        application=application,
        rental_property=prop,
        landlord=landlord,
        tenant=tenant,
        status=TenancyStatus.PENDING_PAYMENT,
        monthly_rent=prop.monthly_rent,
        advance_months=prop.advance_months,
        advance_amount=prop.monthly_rent * prop.advance_months,
        start_date=application.move_in_date,
        end_date=application.move_in_date + timedelta(days=365),
    )


def make_active_tenancy_with_schedule(first_due_offset_days=30, instalment_count=3):
    """
    Tenancy in ACTIVE with an ACCEPTED Proposal carrying a 3-entry
    instalment_schedule, for instalment-payment tests. Pass a negative
    first_due_offset_days to get a schedule that's already overdue.
    """
    tenancy = make_pending_payment_tenancy()
    tenancy.status = TenancyStatus.ACTIVE
    tenancy.save(update_fields=["status"])

    schedule = [
        {
            "due_date": (date.today() + timedelta(days=first_due_offset_days + 30 * i)).isoformat(),
            "amount": str(Decimal("500.00")),
        }
        for i in range(instalment_count)
    ]

    Proposal.objects.create(
        tenancy=tenancy,
        proposed_by=tenancy.landlord,
        status=ProposalStatus.ACCEPTED,
        advance_months=tenancy.advance_months,
        instalment_count=instalment_count,
        instalment_schedule=schedule,
    )

    return tenancy, schedule
