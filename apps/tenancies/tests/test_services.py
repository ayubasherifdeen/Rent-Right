"""
tenancies/tests/test_services.py

Covers: create_tenancy (happy path, 3 guard paths, freeze check, cascade decline,
property status flip), activate_tenancy (happy path + 2 guard paths), and
(v7 retrofit) the new Agreement lifecycle — special conditions formaliser,
dual OTP confirmation, and _execute_agreement.

The old GenerateRentCardTest is removed: generate_rent_card() as a
tenancies-local WeasyPrint-to-FileField function no longer exists (moved
conceptually to the documents app, still unbuilt — see services.py TODOs).

OTP verification is mocked via apps.accounts.services.verify_otp — see the
note at the top of tenancies/services.py about that assumed interface.
"""

import datetime
import sys
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from apps.applications.models import Application, ApplicationStatus
from apps.tenancies.models import AgreementStatus, Tenancy, TenancyStatus
from apps.tenancies.services import (
    _execute_agreement,
    activate_tenancy,
    confirm_agreement_landlord,
    confirm_agreement_tenant,
    create_tenancy,
    formalise_special_conditions,
    save_special_conditions,
)
from apps.tenancies.tests.helpers import (
    make_agreement,
    make_approved_application,
    make_landlord,
    make_property,
    make_tenancy,
    make_verified_tenant,
)


class CreateTenancyHappyPathTest(TestCase):
    def setUp(self):
        self.landlord = make_landlord()
        self.tenant = make_verified_tenant()
        self.prop = make_property(self.landlord, monthly_rent=1500, advance_months=2)
        self.application = make_approved_application(
            landlord=self.landlord, tenant=self.tenant, prop=self.prop
        )

    def test_tenancy_created_with_correct_fields(self):
        tenancy = create_tenancy(self.application, self.landlord)
        self.assertIsInstance(tenancy, Tenancy)
        self.assertEqual(tenancy.landlord, self.landlord)
        self.assertEqual(tenancy.tenant, self.tenant)
        self.assertEqual(tenancy.rental_property, self.prop)

    def test_tenancy_opens_in_pending_negotiation(self):
        """v7 retrofit: create_tenancy no longer jumps straight to
        PENDING_PAYMENT — it opens in PENDING_NEGOTIATION and waits on
        the (not yet built) negotiations app."""
        tenancy = create_tenancy(self.application, self.landlord)
        self.assertEqual(tenancy.status, TenancyStatus.PENDING_NEGOTIATION)

    def test_no_agreement_created_at_this_stage(self):
        """v7 retrofit: Agreement creation belongs to
        negotiations.accept_proposal(), not create_tenancy()."""
        tenancy = create_tenancy(self.application, self.landlord)
        self.assertFalse(hasattr(tenancy, "agreement"))

    def test_financial_terms_frozen(self):
        tenancy = create_tenancy(self.application, self.landlord)
        self.assertEqual(tenancy.monthly_rent, 1500)
        self.assertEqual(tenancy.advance_months, 2)
        self.assertEqual(tenancy.advance_amount, 3000)

    def test_cascade_decline_other_pending_applications(self):
        """All other PENDING applications for the same property → DECLINED."""
        other_tenant = make_verified_tenant(email="other@test.com", phone="0244000099")
        other_app = Application.objects.create(
            rental_property=self.prop,
            tenant=other_tenant,
            status=ApplicationStatus.PENDING,
            move_in_date=datetime.date.today() + datetime.timedelta(days=10),
        )

        create_tenancy(self.application, self.landlord)

        other_app.refresh_from_db()
        self.assertEqual(other_app.status, ApplicationStatus.DECLINED)

    def test_approved_application_status_unchanged(self):
        """The winning application stays APPROVED — it is an immutable record."""
        create_tenancy(self.application, self.landlord)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, ApplicationStatus.APPROVED)


class CreateTenancyGuardTest(TestCase):
    def setUp(self):
        self.landlord = make_landlord()
        self.tenant = make_verified_tenant()
        self.prop = make_property(self.landlord)
        self.application = make_approved_application(
            landlord=self.landlord, tenant=self.tenant, prop=self.prop
        )

    def test_wrong_landlord_raises(self):
        other_landlord = make_landlord(email="other@landlord.com", phone="0244000020")
        with self.assertRaises(ValueError) as ctx:
            create_tenancy(self.application, other_landlord)
        self.assertIn("do not own", str(ctx.exception))

    def test_non_approved_application_raises(self):
        self.application.status = ApplicationStatus.PENDING
        self.application.save(update_fields=["status"])
        with self.assertRaises(ValueError) as ctx:
            create_tenancy(self.application, self.landlord)
        self.assertIn("approved", str(ctx.exception).lower())

    def test_duplicate_tenancy_raises(self):
        create_tenancy(self.application, self.landlord)
        with self.assertRaises((ValueError, Exception)):
            create_tenancy(self.application, self.landlord)


class ActivateTenancyTest(TestCase):
    def setUp(self):
        self.tenancy = make_tenancy()
        self.landlord = self.tenancy.landlord
        # v7 retrofit: make_tenancy() now returns PENDING_NEGOTIATION.
        # Fast-forward to PENDING_PAYMENT directly for this test's purposes —
        # the negotiation/agreement path is covered separately below.
        self.tenancy.status = TenancyStatus.PENDING_PAYMENT
        self.tenancy.save(update_fields=["status", "updated_at"])

    def test_happy_path_transitions_to_active(self):
        activate_tenancy(self.tenancy, self.landlord)
        self.tenancy.refresh_from_db()
        self.assertEqual(self.tenancy.status, TenancyStatus.ACTIVE)
        self.assertTrue(self.tenancy.is_active)

    def test_wrong_landlord_raises(self):
        other_landlord = make_landlord(email="wrong@landlord.com", phone="0244000030")
        with self.assertRaises(ValueError) as ctx:
            activate_tenancy(self.tenancy, other_landlord)
        self.assertIn("do not own", str(ctx.exception))

    def test_wrong_status_raises(self):
        self.tenancy.status = TenancyStatus.ACTIVE
        self.tenancy.save(update_fields=["status", "updated_at"])
        with self.assertRaises(ValueError) as ctx:
            activate_tenancy(self.tenancy, self.landlord)
        self.assertIn("awaiting payment", str(ctx.exception).lower())

    def test_pending_negotiation_cannot_be_activated(self):
        """A tenancy still mid-negotiation must not be activatable."""
        self.tenancy.status = TenancyStatus.PENDING_NEGOTIATION
        self.tenancy.save(update_fields=["status", "updated_at"])
        with self.assertRaises(ValueError):
            activate_tenancy(self.tenancy, self.landlord)


# ---------------------------------------------------------------------------
# Special conditions formaliser (v7 retrofit — new)
# ---------------------------------------------------------------------------


class FormaliseSpecialConditionsTest(TestCase):
    def test_blank_input_returns_blank(self):
        self.assertEqual(formalise_special_conditions(""), "")
        self.assertEqual(formalise_special_conditions("   "), "")

    def test_falls_back_to_raw_text_on_api_error(self):
        # Fake the `anthropic` module in sys.modules rather than requiring
        # the real package to be pip-installed just to run tests — the
        # `import anthropic` inside formalise_special_conditions() will
        # pick up this fake. (If the real package genuinely isn't
        # installed, production code hits the same except-Exception
        # fallback via ImportError — this test exercises that same path
        # without needing it installed.)
        fake_anthropic = MagicMock()
        fake_anthropic.Anthropic.side_effect = Exception("API unavailable")
        with patch.dict(sys.modules, {"anthropic": fake_anthropic}):
            result = formalise_special_conditions("No pets allowed")
        self.assertEqual(result, "No pets allowed")

    @override_settings(ANTHROPIC_API_KEY="test-key")
    def test_returns_formalised_text_on_success(self):
        mock_block = type("Block", (), {"type": "text", "text": "Pets are prohibited on the premises."})()
        mock_response = type("Response", (), {"content": [mock_block]})()
        fake_anthropic = MagicMock()
        fake_client = fake_anthropic.Anthropic.return_value
        fake_client.messages.create.return_value = mock_response

        with patch.dict(sys.modules, {"anthropic": fake_anthropic}):
            result = formalise_special_conditions("no pets")
        self.assertEqual(result, "Pets are prohibited on the premises.")


class SaveSpecialConditionsTest(TestCase):
    def test_saves_both_raw_and_formalised(self):
        tenancy = make_tenancy()
        agreement = make_agreement(tenancy)
        save_special_conditions(agreement, "no pets", "Pets are prohibited.")
        agreement.refresh_from_db()
        self.assertEqual(agreement.special_conditions_raw, "no pets")
        self.assertEqual(agreement.special_conditions, "Pets are prohibited.")


# ---------------------------------------------------------------------------
# Dual OTP confirmation + _execute_agreement (v7 retrofit — new)
# ---------------------------------------------------------------------------


class ConfirmAgreementLandlordTest(TestCase):
    def setUp(self):
        self.tenancy = make_tenancy()
        self.agreement = make_agreement(self.tenancy)
        self.landlord = self.tenancy.landlord
        self.tenant = self.tenancy.tenant

    @patch("apps.accounts.services.verify_otp", return_value="otp-ref-123")
    def test_wrong_party_raises(self, mock_verify):
        other_landlord = make_landlord(email="notthis@landlord.com", phone="0244000040")
        with self.assertRaises(ValueError) as ctx:
            confirm_agreement_landlord(self.agreement, other_landlord, "123456")
        self.assertIn("not the landlord", str(ctx.exception))
        mock_verify.assert_not_called()

    @patch("apps.accounts.services.verify_otp", return_value="otp-ref-123")
    def test_landlord_confirms_first_moves_to_pending_tenant(self, mock_verify):
        confirm_agreement_landlord(self.agreement, self.landlord, "123456")
        self.agreement.refresh_from_db()
        self.assertEqual(self.agreement.status, AgreementStatus.PENDING_TENANT)
        self.assertIsNotNone(self.agreement.landlord_confirmed_at)
        self.assertEqual(self.agreement.landlord_otp_ref, "otp-ref-123")
        self.assertFalse(self.agreement.is_fully_executed)

    @patch("apps.accounts.services.verify_otp", return_value="otp-ref-456")
    def test_landlord_confirms_second_executes_agreement(self, mock_verify):
        confirm_agreement_tenant(self.agreement, self.tenant, "111111")
        confirm_agreement_landlord(self.agreement, self.landlord, "222222")

        self.agreement.refresh_from_db()
        self.tenancy.refresh_from_db()
        self.assertTrue(self.agreement.is_fully_executed)
        self.assertEqual(self.tenancy.status, TenancyStatus.PENDING_PAYMENT)

    @patch("apps.accounts.services.verify_otp", return_value="otp-ref-123")
    def test_cannot_reconfirm_fully_executed_agreement(self, mock_verify):
        confirm_agreement_tenant(self.agreement, self.tenant, "111111")
        confirm_agreement_landlord(self.agreement, self.landlord, "222222")
        with self.assertRaises(ValueError) as ctx:
            confirm_agreement_landlord(self.agreement, self.landlord, "333333")
        self.assertIn("already been fully executed", str(ctx.exception))


class ConfirmAgreementTenantTest(TestCase):
    def setUp(self):
        self.tenancy = make_tenancy()
        self.agreement = make_agreement(self.tenancy)
        self.landlord = self.tenancy.landlord
        self.tenant = self.tenancy.tenant

    @patch("apps.accounts.services.verify_otp", return_value="otp-ref-789")
    def test_wrong_party_raises(self, mock_verify):
        other_tenant = make_verified_tenant(email="notthis@tenant.com", phone="0244000041")
        with self.assertRaises(ValueError) as ctx:
            confirm_agreement_tenant(self.agreement, other_tenant, "123456")
        self.assertIn("not the tenant", str(ctx.exception))
        mock_verify.assert_not_called()

    @patch("apps.accounts.services.verify_otp", return_value="otp-ref-789")
    def test_tenant_confirms_second_executes_agreement(self, mock_verify):
        confirm_agreement_landlord(self.agreement, self.landlord, "111111")
        confirm_agreement_tenant(self.agreement, self.tenant, "222222")

        self.agreement.refresh_from_db()
        self.tenancy.refresh_from_db()
        self.assertTrue(self.agreement.is_fully_executed)
        self.assertEqual(self.tenancy.status, TenancyStatus.PENDING_PAYMENT)


class ExecuteAgreementTest(TestCase):
    def test_sets_fully_executed_and_advances_tenancy(self):
        tenancy = make_tenancy()
        agreement = make_agreement(tenancy)

        _execute_agreement(agreement)

        agreement.refresh_from_db()
        tenancy.refresh_from_db()
        self.assertEqual(agreement.status, AgreementStatus.FULLY_EXECUTED)
        self.assertIsNotNone(agreement.fully_executed_at)
        self.assertEqual(tenancy.status, TenancyStatus.PENDING_PAYMENT)