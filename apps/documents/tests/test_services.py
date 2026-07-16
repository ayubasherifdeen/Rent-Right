"""
documents/tests/test_services.py

Written to the same conventions as the tenancies test suite (handoff
v8 §2.10) — mocking the heavy dependency (WeasyPrint here, `anthropic`
there) rather than requiring it importable / functional in the test
environment.

⚠️ NOT RUN this session — no project files were available to run
against (only the v8 handoff markdown was uploaded, no actual
tenancies/ or accounts/ source). Treat this as a first draft: run it
against your real project and fix whatever the real `Tenancy` /
`Agreement` field names turn out to be (see ASSUMPTION notes in
services.py and views.py).
"""

from unittest.mock import MagicMock, patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase

from apps.documents.models import Document, DocumentType
from apps.documents import services

# ASSUMPTION: these two helpers exist in apps/tenancies/tests/helpers.py,
# analogous to make_agreement() referenced in handoff v8 §2.6.
from apps.tenancies.tests.helpers import (
    make_tenancy,
    make_agreement,
    make_landlord,
    make_verified_tenant,
    make_approved_application,
)


class GenerateRentCardTests(TestCase):
    def setUp(self):
        self.tenancy = make_tenancy()

    @patch("apps.documents.services.HTML")
    def test_creates_document_generic_fk_to_tenancy(self, mock_html):
        mock_html.return_value.write_pdf.return_value = b"%PDF-fake-bytes"

        document = services.generate_rent_card(self.tenancy)

        self.assertEqual(document.document_type, DocumentType.RENT_CARD)
        self.assertEqual(document.content_type, ContentType.objects.get_for_model(self.tenancy))
        self.assertEqual(document.object_id, self.tenancy.pk)
        self.assertTrue(document.file.name.startswith("documents/"))

    @patch("apps.documents.services.HTML")
    def test_renders_rent_card_template(self, mock_html):
        mock_html.return_value.write_pdf.return_value = b"%PDF-fake-bytes"
        with patch("apps.documents.services.render_to_string") as mock_render:
            mock_render.return_value = "<html></html>"
            services.generate_rent_card(self.tenancy)
            template_name = mock_render.call_args[0][0]
            self.assertEqual(template_name, "tenancies/rent_card_template.html")


class GenerateTenancyAgreementTests(TestCase):
    def setUp(self):
        self.tenancy = make_tenancy()
        self.agreement = make_agreement(tenancy=self.tenancy)

    @patch("apps.documents.services.HTML")
    def test_creates_document_generic_fk_to_agreement(self, mock_html):
        mock_html.return_value.write_pdf.return_value = b"%PDF-fake-bytes"

        document = services.generate_tenancy_agreement(self.agreement)

        self.assertEqual(document.document_type, DocumentType.TENANCY_AGREEMENT)
        self.assertEqual(document.content_type, ContentType.objects.get_for_model(self.agreement))
        self.assertEqual(document.object_id, self.agreement.pk)


class GetDocumentsForTests(TestCase):
    @patch("apps.documents.services.HTML")
    def test_returns_only_documents_for_given_object(self, mock_html):
        mock_html.return_value.write_pdf.return_value = b"%PDF-fake-bytes"

        # NOTE: cannot call make_tenancy() twice bare here — it defaults
        # to a hardcoded landlord email ("landlord2@test.com") when no
        # landlord/application is passed, so two bare calls collide on
        # accounts_user.email's unique constraint. Same bug pattern
        # flagged in tenancies handoff v8 §2.10. Building each tenancy
        # from explicit, distinct landlord+tenant instead.
        landlord_a = make_landlord(email="landlord_a@test.com", phone="0244000021")
        tenant_a = make_verified_tenant(email="tenant_a@test.com", phone="0244000031")
        application_a = make_approved_application(landlord=landlord_a, tenant=tenant_a)
        tenancy_a = make_tenancy(application=application_a)

        landlord_b = make_landlord(email="landlord_b@test.com", phone="0244000022")
        tenant_b = make_verified_tenant(email="tenant_b@test.com", phone="0244000032")
        application_b = make_approved_application(landlord=landlord_b, tenant=tenant_b)
        tenancy_b = make_tenancy(application=application_b)

        services.generate_rent_card(tenancy_a)
        services.generate_rent_card(tenancy_b)

        results = services.get_documents_for(tenancy_a)
        self.assertEqual(results.count(), 1)
        self.assertEqual(results.first().object_id, tenancy_a.pk)
