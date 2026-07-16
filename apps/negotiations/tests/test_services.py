"""
ASSUMED INTERFACE, NOT CONFIRMED: these tests import
apps.tenancies.tests.helpers.make_tenancy and assume it accepts
landlord/tenant User instances (created here with distinct emails per
the v8/v9 §2.10 collision bug) and returns a Tenancy in
PENDING_NEGOTIATION by default. Not verified against the real project
this session — first thing to check on the next real test run, same
category as the object_id bug in documents (handoff v9 §2.2): if this
app's very first real run errors out, check assumed-interface mismatches
here before assuming the negotiations logic itself is wrong.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.negotiations.models import ProposalStatus
from apps.negotiations.services import (
    accept_proposal,
    counter_proposal,
    get_current_proposal,
    get_proposal_chain,
    open_negotiation,
    reject_proposal,
)
from apps.negotiations.tests.helpers import make_proposal, unique_email
from apps.tenancies.tests.helpers import make_tenancy  # ASSUMED INTERFACE

User = get_user_model()


class OpenNegotiationTests(TestCase):
    def setUp(self):
        self.landlord = User.objects.create_user(email=unique_email("landlord"), password="x")
        self.tenant = User.objects.create_user(email=unique_email("tenant"), password="x")
        self.tenancy = make_tenancy(landlord=self.landlord, tenant=self.tenant)

    def test_opening_proposal_is_landlord_authored(self):
        # Listing terms mocked — see ASSUMED INTERFACE note in
        # negotiations/services.py re: default_advance_months etc.
        self.tenancy.rental_property.listing.default_advance_months = 2
        self.tenancy.rental_property.listing.default_instalment_count = 2
        self.tenancy.rental_property.listing.default_instalment_schedule = [
            {"due_date": "2026-08-01", "amount": "500.00"},
            {"due_date": "2026-09-01", "amount": "500.00"},
        ]

        proposal = open_negotiation(self.tenancy)

        self.assertEqual(proposal.proposed_by, self.landlord)
        self.assertIsNone(proposal.previous_proposal)
        self.assertEqual(proposal.status, ProposalStatus.PENDING)
        self.assertTrue(proposal.is_opening_proposal)


class CounterProposalTests(TestCase):
    def setUp(self):
        self.landlord = User.objects.create_user(email=unique_email("landlord"), password="x")
        self.tenant = User.objects.create_user(email=unique_email("tenant"), password="x")
        self.tenancy = make_tenancy(landlord=self.landlord, tenant=self.tenant)
        self.opening = make_proposal(self.tenancy, proposed_by=self.landlord)

    def test_tenant_can_counter_landlord_proposal(self):
        new_proposal = counter_proposal(
            previous_proposal=self.opening,
            proposed_by=self.tenant,
            advance_months=1,
            instalment_count=6,
            instalment_schedule=[{"due_date": "2026-08-01", "amount": "500.00"}],
        )
        self.opening.refresh_from_db()

        self.assertEqual(self.opening.status, ProposalStatus.COUNTERED)
        self.assertEqual(new_proposal.previous_proposal, self.opening)
        self.assertEqual(new_proposal.proposed_by, self.tenant)
        self.assertEqual(new_proposal.status, ProposalStatus.PENDING)

    def test_cannot_counter_own_proposal(self):
        with self.assertRaises(ValueError):
            counter_proposal(
                previous_proposal=self.opening,
                proposed_by=self.landlord,
                advance_months=1,
                instalment_count=6,
                instalment_schedule=[],
            )

    def test_cannot_counter_already_countered_proposal(self):
        counter_proposal(
            previous_proposal=self.opening,
            proposed_by=self.tenant,
            advance_months=1,
            instalment_count=6,
            instalment_schedule=[],
        )
        with self.assertRaises(ValueError):
            counter_proposal(
                previous_proposal=self.opening,
                proposed_by=self.tenant,
                advance_months=2,
                instalment_count=3,
                instalment_schedule=[],
            )


class AcceptProposalTests(TestCase):
    def setUp(self):
        self.landlord = User.objects.create_user(email=unique_email("landlord"), password="x")
        self.tenant = User.objects.create_user(email=unique_email("tenant"), password="x")
        self.tenancy = make_tenancy(landlord=self.landlord, tenant=self.tenant)
        self.proposal = make_proposal(self.tenancy, proposed_by=self.landlord)

    def test_tenant_accepting_creates_agreement(self):
        agreement = accept_proposal(self.proposal, accepted_by=self.tenant)
        self.proposal.refresh_from_db()

        self.assertEqual(self.proposal.status, ProposalStatus.ACCEPTED)
        self.assertEqual(agreement.tenancy, self.tenancy)

    def test_tenant_accepting_advances_tenancy_status(self):
        from apps.tenancies.models import TenancyStatus

        accept_proposal(self.proposal, accepted_by=self.tenant)
        self.tenancy.refresh_from_db()

        self.assertEqual(self.tenancy.status, TenancyStatus.PENDING_AGREEMENT)

    def test_cannot_accept_own_proposal(self):
        with self.assertRaises(ValueError):
            accept_proposal(self.proposal, accepted_by=self.landlord)

    def test_agreement_has_no_instalment_fields_terms_stay_on_proposal(self):
        # Documents this session's option-2 decision at the test level:
        # Agreement is thin, Proposal remains the source of truth.
        agreement = accept_proposal(self.proposal, accepted_by=self.tenant)
        self.assertFalse(hasattr(agreement, "advance_months"))
        self.assertFalse(hasattr(agreement, "instalment_schedule"))


class RejectProposalTests(TestCase):
    def setUp(self):
        self.landlord = User.objects.create_user(email=unique_email("landlord"), password="x")
        self.tenant = User.objects.create_user(email=unique_email("tenant"), password="x")
        self.tenancy = make_tenancy(landlord=self.landlord, tenant=self.tenant)
        self.proposal = make_proposal(self.tenancy, proposed_by=self.landlord)

    def test_reject_marks_status(self):
        reject_proposal(self.proposal, rejected_by=self.tenant)
        self.proposal.refresh_from_db()
        self.assertEqual(self.proposal.status, ProposalStatus.REJECTED)


class ChainHelperTests(TestCase):
    def setUp(self):
        self.landlord = User.objects.create_user(email=unique_email("landlord"), password="x")
        self.tenant = User.objects.create_user(email=unique_email("tenant"), password="x")
        self.tenancy = make_tenancy(landlord=self.landlord, tenant=self.tenant)
        self.opening = make_proposal(self.tenancy, proposed_by=self.landlord)
        self.counter = make_proposal(
            self.tenancy, proposed_by=self.tenant, previous_proposal=self.opening
        )

    def test_get_current_proposal_returns_latest(self):
        self.assertEqual(get_current_proposal(self.tenancy), self.counter)

    def test_get_proposal_chain_returns_oldest_first(self):
        chain = list(get_proposal_chain(self.tenancy))
        self.assertEqual(chain, [self.opening, self.counter])
