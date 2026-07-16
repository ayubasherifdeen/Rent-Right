"""
tenancies/tests/test_models.py

Covers: UUID PK, end_date calendar-month computation, advance_amount storage,
OneToOne uniqueness enforcement, __str__, status default, predicate properties,
and (v7 retrofit) the new Agreement model.
"""

import datetime

from dateutil.relativedelta import relativedelta
from django.test import TestCase

from apps.tenancies.models import Agreement, AgreementStatus, Tenancy, TenancyStatus
from apps.tenancies.tests.helpers import (
    make_agreement,
    make_approved_application,
    make_landlord,
    make_property,
    make_tenancy,
    make_verified_tenant,
)


class TenancyUUIDTest(TestCase):
    def test_uuid_pk_auto_assigned(self):
        tenancy = make_tenancy()
        self.assertIsNotNone(tenancy.id)
        self.assertEqual(len(str(tenancy.id)), 36)  # standard UUID string length


class TenancyEndDateTest(TestCase):
    """
    end_date must use calendar months (relativedelta), not 30-day approximations.
    """

    def _make_tenancy_with_lease(self, lease_term_months, start_offset_days=14):
        landlord = make_landlord()
        prop = make_property(landlord, lease_term_months=lease_term_months)
        tenant = make_verified_tenant()
        app = make_approved_application(landlord=landlord, tenant=tenant, prop=prop)
        app.move_in_date = datetime.date.today() + datetime.timedelta(days=start_offset_days)
        app.save(update_fields=["move_in_date"])
        return make_tenancy(application=app, landlord=landlord)

    def test_end_date_12_months(self):
        tenancy = self._make_tenancy_with_lease(12)
        expected = tenancy.start_date + relativedelta(months=12)
        self.assertEqual(tenancy.end_date, expected)

    def test_end_date_6_months(self):
        tenancy = self._make_tenancy_with_lease(6)
        expected = tenancy.start_date + relativedelta(months=6)
        self.assertEqual(tenancy.end_date, expected)

    def test_end_date_24_months(self):
        tenancy = self._make_tenancy_with_lease(24)
        expected = tenancy.start_date + relativedelta(months=24)
        self.assertEqual(tenancy.end_date, expected)


class TenancyAdvanceAmountTest(TestCase):
    def test_advance_amount_frozen_at_creation(self):
        """advance_amount is stored, not computed live — changing property rent
        after tenancy creation must not affect the stored value."""
        landlord = make_landlord()
        prop = make_property(landlord, monthly_rent=2000, advance_months=3)
        tenant = make_verified_tenant()
        app = make_approved_application(landlord=landlord, tenant=tenant, prop=prop)
        tenancy = make_tenancy(application=app, landlord=landlord)

        self.assertEqual(tenancy.advance_amount, 2000 * 3)

        # Simulate landlord editing the listing price after tenancy creation.
        prop.monthly_rent = 9999
        prop.save(update_fields=["monthly_rent", "updated_at"])

        # Re-fetch from DB — advance_amount must be unchanged.
        tenancy.refresh_from_db()
        self.assertEqual(tenancy.advance_amount, 6000)


class TenancyOneToOneTest(TestCase):
    def test_duplicate_tenancy_on_same_application_raises(self):
        """OneToOneField must block a second tenancy on the same application."""
        tenancy = make_tenancy()
        with self.assertRaises(Exception):
            # This should raise either ValueError (service guard) or IntegrityError (DB).
            from apps.tenancies.services import create_tenancy
            create_tenancy(tenancy.application, tenancy.landlord)


class TenancyStrTest(TestCase):
    def test_str_contains_tenant_and_property(self):
        tenancy = make_tenancy()
        s = str(tenancy)
        self.assertIn(tenancy.tenant.get_full_name(), s)
        self.assertIn(tenancy.rental_property.title, s)


class TenancyStatusDefaultTest(TestCase):
    def test_default_status_is_pending_negotiation(self):
        """v7 retrofit: tenancies now open in PENDING_NEGOTIATION, not
        PENDING_PAYMENT."""
        tenancy = make_tenancy()
        self.assertEqual(tenancy.status, TenancyStatus.PENDING_NEGOTIATION)
        self.assertTrue(tenancy.is_pending_negotiation)
        self.assertFalse(tenancy.is_pending_payment)
        self.assertFalse(tenancy.is_active)


# ---------------------------------------------------------------------------
# Agreement model (v7 retrofit — new)
# ---------------------------------------------------------------------------


class AgreementDefaultsTest(TestCase):
    def test_agreement_defaults_to_pending_landlord(self):
        tenancy = make_tenancy()
        agreement = make_agreement(tenancy)
        self.assertEqual(agreement.status, AgreementStatus.PENDING_LANDLORD)
        self.assertFalse(agreement.is_fully_executed)
        self.assertIsNone(agreement.landlord_confirmed_at)
        self.assertIsNone(agreement.tenant_confirmed_at)
        self.assertIsNone(agreement.fully_executed_at)

    def test_special_conditions_blank_by_default(self):
        tenancy = make_tenancy()
        agreement = make_agreement(tenancy)
        self.assertEqual(agreement.special_conditions_raw, "")
        self.assertEqual(agreement.special_conditions, "")


class AgreementOneToOneTest(TestCase):
    def test_duplicate_agreement_on_same_tenancy_raises(self):
        tenancy = make_tenancy()
        make_agreement(tenancy)
        with self.assertRaises(Exception):
            Agreement.objects.create(tenancy=tenancy)


class AgreementStrTest(TestCase):
    def test_str_contains_tenancy_id_and_status(self):
        tenancy = make_tenancy()
        agreement = make_agreement(tenancy)
        s = str(agreement)
        self.assertIn(str(tenancy.id), s)
        self.assertIn(agreement.get_status_display(), s)


class AgreementUUIDTest(TestCase):
    def test_uuid_pk_auto_assigned(self):
        tenancy = make_tenancy()
        agreement = make_agreement(tenancy)
        self.assertIsNotNone(agreement.id)
        self.assertEqual(len(str(agreement.id)), 36)
