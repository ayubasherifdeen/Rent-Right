"""
Same ASSUMED INTERFACE caveat as test_services.py re: make_tenancy().
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.negotiations.models import ProposalStatus
from apps.negotiations.tests.helpers import make_proposal, unique_email
from apps.tenancies.tests.helpers import make_tenancy  # ASSUMED INTERFACE

User = get_user_model()


class NegotiationDetailAccessTests(TestCase):
    def setUp(self):
        self.landlord = User.objects.create_user(email=unique_email("landlord"), password="x")
        self.tenant = User.objects.create_user(email=unique_email("tenant"), password="x")
        self.stranger = User.objects.create_user(email=unique_email("stranger"), password="x")
        self.staff = User.objects.create_user(
            email=unique_email("staff"), password="x", is_staff=True
        )
        self.tenancy = make_tenancy(landlord=self.landlord, tenant=self.tenant)
        self.proposal = make_proposal(self.tenancy, proposed_by=self.landlord)
        self.url = reverse("negotiations:negotiation_detail", args=[self.tenancy.id])

    def test_landlord_can_view(self):
        self.client.force_login(self.landlord)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_tenant_can_view(self):
        self.client.force_login(self.tenant)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_staff_can_view(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_stranger_gets_404_not_403(self):
        self.client.force_login(self.stranger)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)


class AcceptProposalViewTests(TestCase):
    def setUp(self):
        self.landlord = User.objects.create_user(email=unique_email("landlord"), password="x")
        self.tenant = User.objects.create_user(email=unique_email("tenant"), password="x")
        self.tenancy = make_tenancy(landlord=self.landlord, tenant=self.tenant)
        self.proposal = make_proposal(self.tenancy, proposed_by=self.landlord)
        self.url = reverse("negotiations:accept_proposal", args=[self.proposal.id])

    def test_get_not_allowed(self):
        self.client.force_login(self.tenant)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_tenant_accept_redirects_to_agreement(self):
        self.client.force_login(self.tenant)
        response = self.client.post(self.url)
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, ProposalStatus.ACCEPTED)
        self.assertEqual(response.status_code, 302)

    def test_landlord_cannot_accept_own_proposal(self):
        self.client.force_login(self.landlord)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 400)

    def test_stranger_gets_404(self):
        stranger = User.objects.create_user(email=unique_email("stranger"), password="x")
        self.client.force_login(stranger)
        self.assertEqual(self.client.post(self.url).status_code, 404)


class RejectProposalViewTests(TestCase):
    def setUp(self):
        self.landlord = User.objects.create_user(email=unique_email("landlord"), password="x")
        self.tenant = User.objects.create_user(email=unique_email("tenant"), password="x")
        self.tenancy = make_tenancy(landlord=self.landlord, tenant=self.tenant)
        self.proposal = make_proposal(self.tenancy, proposed_by=self.landlord)
        self.url = reverse("negotiations:reject_proposal", args=[self.proposal.id])

    def test_tenant_reject_redirects(self):
        self.client.force_login(self.tenant)
        response = self.client.post(self.url)
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, ProposalStatus.REJECTED)
        self.assertEqual(response.status_code, 302)
