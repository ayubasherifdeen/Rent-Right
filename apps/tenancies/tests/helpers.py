"""
tenancies/tests/helpers.py

Builds on applications/tests/helpers.py. Provides ready-made objects
at each stage of the tenancy pipeline so individual tests stay focused.

v7 retrofit — added:
  make_agreement() — creates an Agreement directly on a tenancy,
  simulating what negotiations.accept_proposal() will do once that app
  exists (handoff §16). Needed because there's currently no in-app path
  from PENDING_NEGOTIATION to an Agreement being created.
"""

import datetime

from apps.accounts.models import User
from apps.applications.models import Application, ApplicationStatus
from apps.listings.models import Property


# ---------------------------------------------------------------------------
# User factories (mirrors applications/tests/helpers.py pattern)
# ---------------------------------------------------------------------------


def make_landlord(email="landlord@test.com", phone="0244000001"):
    user = User.objects.create_user(
        email=email,
        username=email,
        password="testpass123",
        first_name="Kwame",
        last_name="Mensah",
        phone_number=phone,
    )
    profile = user.userprofile
    profile.role = "landlord"
    profile.save()
    return user


def make_verified_tenant(email="tenant@test.com", phone="0244000002"):
    user = User.objects.create_user(
        email=email,
        username=email,
        password="testpass123",
        first_name="Ama",
        last_name="Owusu",
        phone_number=phone,
    )
    user.is_verified = True
    user.save(update_fields=["is_verified"])
    profile = user.userprofile
    profile.role = "tenant"
    profile.save()
    return user


# ---------------------------------------------------------------------------
# Property factory
# ---------------------------------------------------------------------------


def make_property(landlord, status="active", **kwargs):
    defaults = dict(
        title="Test Property",
        property_type="apartment",
        bedrooms=2,
        bathrooms=1,
        address="12 Test Street",
        city="Accra",
        region="Greater Accra",
        monthly_rent=1500,
        advance_months=3,
        lease_term_months=12,
        status=status,
        landlord=landlord,
    )
    defaults.update(kwargs)
    return Property.objects.create(**defaults)


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def make_approved_application(landlord=None, tenant=None, prop=None):
    """
    Returns an Application in APPROVED state, ready for tenancy creation.
    Creates landlord, tenant, and property if not supplied.
    """
    if landlord is None:
        landlord = make_landlord()
    if tenant is None:
        tenant = make_verified_tenant()
    if prop is None:
        prop = make_property(landlord)

    application = Application.objects.create(
        rental_property=prop,
        tenant=tenant,
        status=ApplicationStatus.APPROVED,
        move_in_date=datetime.date.today() + datetime.timedelta(days=14),
    )
    return application


# ---------------------------------------------------------------------------
# Tenancy factory
# ---------------------------------------------------------------------------


def make_tenancy(application=None, landlord=None):
    """
    Calls create_tenancy() so all service-layer side effects are exercised.
    Returns the created Tenancy — status will be PENDING_NEGOTIATION.
    """
    from apps.tenancies.services import create_tenancy

    if application is None:
        if landlord is None:
            landlord = make_landlord(email="landlord2@test.com", phone="0244000010")
        application = make_approved_application(landlord=landlord)
    elif landlord is None:
        landlord = application.rental_property.landlord

    return create_tenancy(application, landlord)


# ---------------------------------------------------------------------------
# Agreement factory (v7 retrofit)
# ---------------------------------------------------------------------------


def make_agreement(tenancy):
    """
    Creates an Agreement directly on a tenancy, bypassing the (not yet
    built) negotiations app. Simulates the object state that
    negotiations.accept_proposal() will produce: an Agreement in
    PENDING_LANDLORD, with the tenancy sitting in PENDING_AGREEMENT.

    Use this to test the Agreement/OTP/_execute_agreement lifecycle in
    isolation from the negotiation flow.
    """
    from apps.tenancies.models import Agreement, TenancyStatus

    tenancy.status = TenancyStatus.PENDING_AGREEMENT
    tenancy.save(update_fields=["status", "updated_at"])

    return Agreement.objects.create(tenancy=tenancy)


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


def future_date(days=30):
    return datetime.date.today() + datetime.timedelta(days=days)
