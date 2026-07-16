"""
documents/tests/test_views.py — access control for download_document.

⚠️ NOT RUN this session — same caveat as test_services.py.
"""

from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse

from apps.tenancies.tests.helpers import make_tenancy, make_agreement, make_landlord
from apps.documents import services


class DownloadDocumentAccessTests(TestCase):
    def setUp(self):
        self.tenancy = make_tenancy()
        with patch("apps.documents.services.HTML") as mock_html:
            mock_html.return_value.write_pdf.return_value = b"%PDF-fake-bytes"
            self.document = services.generate_rent_card(self.tenancy)

    def test_landlord_can_download(self):
        self.client.force_login(self.tenancy.landlord)
        response = self.client.get(reverse("documents:download", args=[self.document.id]))
        self.assertEqual(response.status_code, 200)

    def test_tenant_can_download(self):
        self.client.force_login(self.tenancy.tenant)
        response = self.client.get(reverse("documents:download", args=[self.document.id]))
        self.assertEqual(response.status_code, 200)

    def test_stranger_gets_404_not_403(self):
        # NOTE: not calling make_tenancy() again here — it defaults to
        # a hardcoded landlord email when called bare, which collides
        # with setUp()'s self.tenancy landlord. Same bug pattern as v8
        # §2.10. A stranger just needs to be *some* other authenticated
        # user, not another full tenancy.
        stranger = make_landlord(email="stranger@test.com", phone="0244000099")
        self.client.force_login(stranger)
        response = self.client.get(reverse("documents:download", args=[self.document.id]))
        self.assertEqual(response.status_code, 404)

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(reverse("documents:download", args=[self.document.id]))
        self.assertEqual(response.status_code, 302)
