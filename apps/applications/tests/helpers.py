"""
applications/tests/helpers.py

Factories that build the objects tests need without repeating setup boilerplate.
These mirror the pattern established in listings/tests/helpers.py so the
whole test suite reads consistently.
"""

import datetime
from apps.accounts.models import User
from apps.listings.models import Property
from apps.applications.models import Application, ApplicationStatus


def make_landlord(email='landlord@test.com', phone='0244100001'):
    user = User.objects.create_user(
        email=email, password='testpass123',
        first_name='Kwame', last_name='Mensah', phone_number=phone, username=email
    )
    profile = user.userprofile
    profile.role = 'landlord'
    profile.save()
    return user


def make_verified_tenant(email='tenant@test.com', phone='0244200002'):
    user = User.objects.create_user(
        email=email, password='testpass123',
        first_name='Ama', last_name='Asante', phone_number=phone, username=email
    )
    profile = user.userprofile
    profile.role = 'tenant'
    profile.save()
    user.is_verified = True
    user.save()
    return user


def make_unverified_tenant(email='unverified@test.com', phone='0244300003'):
    user = User.objects.create_user(
        email=email, password='testpass123',
        first_name='Kofi', last_name='Boateng', phone_number=phone, username=email
    )
    profile = user.userprofile
    profile.role = 'tenant'
    profile.save()
    # is_verified defaults to False — do not set it
    return user


def make_property(landlord, status='active', **kwargs):
    defaults = {
        'title':             'Test Apartment',
        'property_type':     'apartment',
        'address':           '5 Osu Road',
        'city':              'Accra',
        'region':            'Greater Accra',
        'bedrooms':          2,
        'bathrooms':         1,
        'monthly_rent':      1500,
        'advance_months':    2,
        'lease_term_months': 12,
        'status':            status,
    }
    defaults.update(kwargs)
    return Property.objects.create(landlord=landlord, **defaults)


def make_application(tenant, property_obj, status=ApplicationStatus.PENDING, **kwargs):
    defaults = {
        'move_in_date': future_date(),
        'message':      '',
        'status':       status,
    }
    defaults.update(kwargs)
    return Application.objects.create(
        tenant=tenant,
        property=property_obj,
        **defaults,
    )


def future_date(days=30):
    return datetime.date.today() + datetime.timedelta(days=days)
