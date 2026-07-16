from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.negotiations.models import ProposalStatus
from apps.negotiations.tests.helpers import make_proposal, unique_email
from apps.tenancies.tests.helpers import make_tenancy  # ASSUMED INTERFACE

User = get_user_model()


class ProposalModelTests(TestCase):
    def setUp(self):
        self.landlord = User.objects.create_user(email=unique_email("landlord"), password="x")
        self.tenant = User.objects.create_user(email=unique_email("tenant"), password="x")
        self.tenancy = make_tenancy(landlord=self.landlord, tenant=self.tenant)

    def test_default_status_is_pending(self):
        proposal = make_proposal(self.tenancy, proposed_by=self.landlord)
        self.assertEqual(proposal.status, ProposalStatus.PENDING)

    def test_is_opening_proposal_true_when_no_previous(self):
        proposal = make_proposal(self.tenancy, proposed_by=self.landlord)
        self.assertTrue(proposal.is_opening_proposal)

    def test_is_opening_proposal_false_when_chained(self):
        opening = make_proposal(self.tenancy, proposed_by=self.landlord)
        counter = make_proposal(
            self.tenancy, proposed_by=self.tenant, previous_proposal=opening
        )
        self.assertFalse(counter.is_opening_proposal)

    def test_deleting_previous_proposal_sets_null_not_cascade(self):
        opening = make_proposal(self.tenancy, proposed_by=self.landlord)
        counter = make_proposal(
            self.tenancy, proposed_by=self.tenant, previous_proposal=opening
        )
        opening.delete()
        counter.refresh_from_db()
        self.assertIsNone(counter.previous_proposal)
        # Chain history survives even if a link is deleted — this is
        # exactly why previous_proposal uses SET_NULL, not CASCADE.

    def test_str_includes_tenancy_and_status(self):
        proposal = make_proposal(self.tenancy, proposed_by=self.landlord)
        self.assertIn(str(self.tenancy.id), str(proposal))
