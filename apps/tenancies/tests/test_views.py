"""
tenancies/tests/test_views.py

Covers: create_tenancy view (POST only, landlord only, 404 bad UUID, redirect);
tenancy_detail access control (landlord ✓, tenant ✓, stranger → 404);
my_tenancies data isolation; landlord_tenancies isolation; and (v7 retrofit)
agreement_detail / confirm_agreement / special_conditions access control.

DownloadRentCardTest is removed — that view/URL no longer exists (rent_card_pdf
moves to the documents vault once that app is built).
"""

import sys
import uuid
from unittest.mock import MagicMock, patch

from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import ManagedProperty, User
from apps.tenancies.models import AgreementStatus
from apps.tenancies.tests.helpers import (
    make_agreement,
    make_approved_application,
    make_landlord,
    make_property,
    make_tenancy,
    make_verified_tenant,
)


class CreateTenancyViewTest(TestCase):
    def setUp(self):
        self.landlord = make_landlord()
        self.tenant = make_verified_tenant()
        self.prop = make_property(self.landlord)
        self.application = make_approved_application(
            landlord=self.landlord, tenant=self.tenant, prop=self.prop
        )
        self.client = Client()
        self.url = reverse("tenancies:create_tenancy", kwargs={"application_pk": self.application.pk})

    def test_get_redirects(self):
        self.client.force_login(self.landlord)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_tenant_cannot_create_tenancy(self):
        self.client.force_login(self.tenant)
        response = self.client.post(self.url)
        # @landlord_required raises PermissionDenied for wrong-role users
        # (confirmed against your accounts/decorators.py — not a redirect).
        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_redirects_to_login(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_404_on_unknown_application_uuid(self):
        self.client.force_login(self.landlord)
        bad_url = reverse("tenancies:create_tenancy", kwargs={"application_pk": uuid.uuid4()})
        response = self.client.post(bad_url)
        self.assertEqual(response.status_code, 404)

    def test_successful_post_redirects_to_tenancy_detail(self):
        self.client.force_login(self.landlord)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("tenancies", response["Location"])

    def test_wrong_landlord_gets_error_and_redirect(self):
        other_landlord = make_landlord(email="other@land.com", phone="0244000050")
        other_landlord.userprofile.role = "landlord"
        other_landlord.userprofile.save()
        self.client.force_login(other_landlord)
        response = self.client.post(self.url)
        # Service raises ValueError → flash + redirect, not 403
        self.assertEqual(response.status_code, 302)


class TenancyDetailAccessTest(TestCase):
    def setUp(self):
        self.tenancy = make_tenancy()
        self.landlord = self.tenancy.landlord
        self.tenant = self.tenancy.tenant
        self.url = reverse("tenancies:tenancy_detail", kwargs={"pk": self.tenancy.pk})

    def test_landlord_can_view(self):
        self.client.force_login(self.landlord)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_tenant_can_view(self):
        self.client.force_login(self.tenant)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_stranger_gets_404(self):
        stranger = make_verified_tenant(email="stranger@test.com", phone="0244000060")
        self.client.force_login(stranger)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)

    def test_unauthenticated_redirected(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_context_has_no_agreement_when_none_exists(self):
        self.client.force_login(self.landlord)
        response = self.client.get(self.url)
        self.assertIsNone(response.context["agreement"])


class MyTenanciesIsolationTest(TestCase):
    def test_tenant_sees_only_own_tenancies(self):
        """Two tenants — each should only see their own tenancy."""
        tenancy_a = make_tenancy()

        landlord_b = make_landlord(email="lb@test.com", phone="0244000070")
        tenant_b = make_verified_tenant(email="tb@test.com", phone="0244000071")
        prop_b = make_property(landlord_b)
        app_b = make_approved_application(landlord=landlord_b, tenant=tenant_b, prop=prop_b)
        make_tenancy(application=app_b, landlord=landlord_b)

        self.client.force_login(tenancy_a.tenant)
        response = self.client.get(reverse("tenancies:my_tenancies"))
        self.assertEqual(response.status_code, 200)
        tenancies_in_ctx = list(response.context["tenancies"])
        self.assertEqual(len(tenancies_in_ctx), 1)
        self.assertEqual(tenancies_in_ctx[0].tenant, tenancy_a.tenant)


class ManagerTenanciesAccessTest(TestCase):
    def setUp(self):
        self.tenancy = make_tenancy()
        self.manager = User.objects.create_user(
            email="manager@test.com",
            username="manager@test.com",
            password="testpass123",
        )
        self.manager.userprofile.role = "property_manager"
        self.manager.userprofile.save(update_fields=["role"])
        ManagedProperty.objects.create(
            property=self.tenancy.rental_property,
            manager=self.manager,
            landlord=self.tenancy.landlord,
            status=ManagedProperty.Status.ACTIVE,
        )

    def test_manager_sees_delegated_tenancies(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("tenancies:landlord_tenancies"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["tenancies"]), [self.tenancy])

    def test_manager_can_view_delegated_tenancy_detail(self):
        self.client.force_login(self.manager)
        response = self.client.get(
            reverse("tenancies:tenancy_detail", kwargs={"pk": self.tenancy.pk})
        )

        self.assertEqual(response.status_code, 200)


# ---------------------------------------------------------------------------
# Agreement detail (v7 retrofit — new)
# ---------------------------------------------------------------------------


class AgreementDetailAccessTest(TestCase):
    def setUp(self):
        self.tenancy = make_tenancy()
        self.agreement = make_agreement(self.tenancy)
        self.landlord = self.tenancy.landlord
        self.tenant = self.tenancy.tenant
        self.url = reverse("tenancies:agreement_detail", kwargs={"pk": self.tenancy.pk})

    def test_landlord_can_view(self):
        self.client.force_login(self.landlord)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_tenant_can_view(self):
        self.client.force_login(self.tenant)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_stranger_gets_404(self):
        stranger = make_verified_tenant(email="stranger3@test.com", phone="0244000090")
        self.client.force_login(stranger)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 404)

    def test_404_when_no_agreement_exists_yet(self):
        """A tenancy still in PENDING_NEGOTIATION has no Agreement — 404, not 500."""
        # NOTE: make_tenancy()/make_approved_application() default to
        # hardcoded emails ("landlord2@test.com" / "tenant@test.com"),
        # which setUp() above already used — building the application
        # explicitly with distinct emails avoids a UNIQUE constraint
        # collision on accounts_user.email.
        other_landlord = make_landlord(email="bare-tenancy-landlord@test.com", phone="0244000092")
        other_tenant = make_verified_tenant(email="bare-tenancy-tenant@test.com", phone="0244000093")
        other_app = make_approved_application(landlord=other_landlord, tenant=other_tenant)
        bare_tenancy = make_tenancy(application=other_app, landlord=other_landlord)
        self.client.force_login(bare_tenancy.landlord)
        url = reverse("tenancies:agreement_detail", kwargs={"pk": bare_tenancy.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)


class ConfirmAgreementViewTest(TestCase):
    def setUp(self):
        self.tenancy = make_tenancy()
        self.agreement = make_agreement(self.tenancy)
        self.landlord = self.tenancy.landlord
        self.tenant = self.tenancy.tenant
        self.url = reverse("tenancies:confirm_agreement", kwargs={"pk": self.tenancy.pk})

    def test_get_redirects(self):
        self.client.force_login(self.landlord)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_stranger_gets_404(self):
        stranger = make_verified_tenant(email="stranger4@test.com", phone="0244000091")
        self.client.force_login(stranger)
        response = self.client.post(self.url, {"otp_code": "123456"})
        self.assertEqual(response.status_code, 404)

    @patch("apps.accounts.services.verify_otp", return_value="ref-1")
    def test_landlord_valid_otp_confirms(self, mock_verify):
        self.client.force_login(self.landlord)
        response = self.client.post(self.url, {"otp_code": "123456"})
        self.assertEqual(response.status_code, 302)
        self.agreement.refresh_from_db()
        self.assertEqual(self.agreement.status, AgreementStatus.PENDING_TENANT)

    @patch("apps.accounts.services.verify_otp", side_effect=ValueError("Invalid or expired code."))
    def test_invalid_otp_flashes_error_and_redirects(self, mock_verify):
        self.client.force_login(self.landlord)
        response = self.client.post(self.url, {"otp_code": "000000"})
        self.assertEqual(response.status_code, 302)
        self.agreement.refresh_from_db()
        self.assertIsNone(self.agreement.landlord_confirmed_at)


class SpecialConditionsViewTest(TestCase):
    def setUp(self):
        self.tenancy = make_tenancy()
        self.agreement = make_agreement(self.tenancy)
        self.landlord = self.tenancy.landlord
        self.tenant = self.tenancy.tenant
        self.url = reverse("tenancies:special_conditions", kwargs={"pk": self.tenancy.pk})

    def test_tenant_cannot_access(self):
        self.client.force_login(self.tenant)
        response = self.client.get(self.url)
        # @landlord_required raises PermissionDenied for wrong-role users.
        self.assertEqual(response.status_code, 403)

    def test_landlord_can_view_form(self):
        self.client.force_login(self.landlord)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

    def test_first_post_shows_review_step_without_saving(self):
        fake_anthropic = MagicMock()
        fake_anthropic.Anthropic.side_effect = Exception("no network in test")
        self.client.force_login(self.landlord)
        with patch.dict(sys.modules, {"anthropic": fake_anthropic}):
            response = self.client.post(self.url, {"raw_text": "no pets"})
        self.assertEqual(response.status_code, 200)
        self.agreement.refresh_from_db()
        # Falls back to raw text on API error, but nothing is saved until confirmed.
        self.assertEqual(self.agreement.special_conditions, "")

    def test_confirmed_post_saves_and_redirects(self):
        self.client.force_login(self.landlord)
        response = self.client.post(
            self.url,
            {"confirm": "1", "raw_text": "no pets", "formalised_text": "Pets are prohibited."},
        )
        self.assertEqual(response.status_code, 302)
        self.agreement.refresh_from_db()
        self.assertEqual(self.agreement.special_conditions, "Pets are prohibited.")