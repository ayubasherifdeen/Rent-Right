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
        # Reads FROZEN Tenancy fields now, not Property — see the
        # frozen-vs-live fix in negotiations/services.py.
        self.tenancy.advance_months = 2
        self.tenancy.monthly_rent = 1000
        self.tenancy.rental_property.payment_cycle = "quarterly"
        self.tenancy.rental_property.save()
        self.tenancy.save()

        proposal = open_negotiation(self.tenancy)

        self.assertEqual(proposal.proposed_by, self.landlord)
        self.assertIsNone(proposal.previous_proposal)
        self.assertEqual(proposal.status, ProposalStatus.PENDING)
        self.assertTrue(proposal.is_opening_proposal)
        self.assertEqual(proposal.advance_months, 2)
        self.assertGreater(proposal.instalment_count, 0)
        self.assertEqual(len(proposal.instalment_schedule), proposal.instalment_count)

    def test_opening_proposal_rejects_over_cap_advance_at_db_level(self):
        # Guards against Property somehow holding an out-of-range value
        # (shouldn't happen given Property's own validator, but Proposal
        # has its own independent check — confirming it actually fires).
        from django.core.exceptions import ValidationError

        proposal = open_negotiation(self.tenancy)
        proposal.advance_months = 99
        with self.assertRaises(ValidationError):
            proposal.full_clean()


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
        )
        self.opening.refresh_from_db()

        self.assertEqual(self.opening.status, ProposalStatus.COUNTERED)
        self.assertEqual(new_proposal.previous_proposal, self.opening)
        self.assertEqual(new_proposal.proposed_by, self.tenant)
        self.assertEqual(new_proposal.status, ProposalStatus.PENDING)
        # Schedule is always derived now — confirm it actually got built,
        # not left empty/unset.
        self.assertEqual(len(new_proposal.instalment_schedule), 6)

    def test_cannot_counter_own_proposal(self):
        with self.assertRaises(ValueError):
            counter_proposal(
                previous_proposal=self.opening,
                proposed_by=self.landlord,
                advance_months=1,
                instalment_count=6,
            )

    def test_cannot_counter_with_advance_over_act_220_cap(self):
        with self.assertRaises(ValueError):
            counter_proposal(
                previous_proposal=self.opening,
                proposed_by=self.tenant,
                advance_months=7,  # Section 25(5) cap is 6
                instalment_count=1,
            )

    def test_cannot_counter_already_countered_proposal(self):
        counter_proposal(
            previous_proposal=self.opening,
            proposed_by=self.tenant,
            advance_months=1,
            instalment_count=6,
        )
        with self.assertRaises(ValueError):
            counter_proposal(
                previous_proposal=self.opening,
                proposed_by=self.tenant,
                advance_months=2,
                instalment_count=3,
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

    def test_accepting_sends_otp_to_both_parties(self):
        from apps.accounts.models import OTP

        accept_proposal(self.proposal, accepted_by=self.tenant)

        self.assertTrue(
            OTP.objects.filter(user=self.landlord, purpose="tenancy_confirm").exists()
        )
        self.assertTrue(
            OTP.objects.filter(user=self.tenant, purpose="tenancy_confirm").exists()
        )


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

    def test_cannot_reject_own_proposal(self):
        with self.assertRaises(ValueError):
            reject_proposal(self.proposal, rejected_by=self.landlord)

    def test_reject_below_round_cap_leaves_tenancy_untouched(self):
        from apps.negotiations.services import MAX_NEGOTIATION_ROUNDS
        from apps.tenancies.models import TenancyStatus

        # Sanity check the test setup actually is below the cap.
        self.assertLess(self.tenancy.proposals.count(), MAX_NEGOTIATION_ROUNDS)

        reject_proposal(self.proposal, rejected_by=self.tenant)
        self.tenancy.refresh_from_db()

        self.assertEqual(self.tenancy.status, TenancyStatus.PENDING_NEGOTIATION)

    def test_rejected_proposal_below_cap_can_still_be_countered(self):
        # This is the actual point of the feature — a reject shouldn't
        # be a dead end below the round cap.
        reject_proposal(self.proposal, rejected_by=self.tenant)
        self.proposal.refresh_from_db()

        new_proposal = counter_proposal(
            previous_proposal=self.proposal,
            proposed_by=self.tenant,
            advance_months=1,
            instalment_count=3,
        )
        self.assertEqual(new_proposal.previous_proposal, self.proposal)
        self.assertEqual(new_proposal.status, ProposalStatus.PENDING)

    def test_reject_at_round_cap_cancels_tenancy_and_reopens_property(self):
        from apps.negotiations.services import MAX_NEGOTIATION_ROUNDS
        from apps.listings.models import ListingStatus
        from apps.tenancies.models import TenancyStatus

        # Lock the property first, same way create_tenancy() does, so
        # we can confirm reject_proposal() actually reverts it.
        prop = self.tenancy.rental_property
        prop.status = ListingStatus.PENDING_PAYMENT
        prop.save(update_fields=["status"])

        # Drive the chain up to one below the cap via alternating
        # counters, then reject the final one to trigger cancellation.
        current = self.proposal
        proposer = self.landlord
        other = self.tenant
        while self.tenancy.proposals.count() < MAX_NEGOTIATION_ROUNDS:
            current = counter_proposal(
                previous_proposal=current,
                proposed_by=other,
                advance_months=1,
                instalment_count=3,
            )
            proposer, other = other, proposer

        reject_proposal(current, rejected_by=other)

        self.tenancy.refresh_from_db()
        prop.refresh_from_db()

        self.assertEqual(self.tenancy.status, TenancyStatus.CANCELLED)
        self.assertEqual(prop.status, ListingStatus.ACTIVE)

    def test_countering_a_cancelled_negotiation_raises(self):
        from apps.negotiations.services import MAX_NEGOTIATION_ROUNDS

        current = self.proposal
        proposer = self.landlord
        other = self.tenant
        while self.tenancy.proposals.count() < MAX_NEGOTIATION_ROUNDS:
            current = counter_proposal(
                previous_proposal=current,
                proposed_by=other,
                advance_months=1,
                instalment_count=3,
            )
            proposer, other = other, proposer

        reject_proposal(current, rejected_by=other)

        with self.assertRaises(ValueError):
            counter_proposal(
                previous_proposal=current,
                proposed_by=proposer,
                advance_months=1,
                instalment_count=3,
            )

    def test_pure_countering_past_cap_cancels_without_any_reject(self):
        # The actual bug being fixed: previously the cap was ONLY
        # checked inside reject_proposal(), so a chain of pure counters
        # (nobody ever explicitly rejecting) could sail past
        # MAX_NEGOTIATION_ROUNDS unchecked. Confirms it's now caught in
        # counter_proposal() itself.
        from apps.negotiations.services import MAX_NEGOTIATION_ROUNDS
        from apps.listings.models import ListingStatus
        from apps.tenancies.models import TenancyStatus

        prop = self.tenancy.rental_property
        prop.status = ListingStatus.PENDING_PAYMENT
        prop.save(update_fields=["status"])

        current = self.proposal
        proposer = self.landlord
        other = self.tenant

        # Drive it all the way to the cap purely via counters.
        while self.tenancy.proposals.count() < MAX_NEGOTIATION_ROUNDS:
            current = counter_proposal(
                previous_proposal=current,
                proposed_by=other,
                advance_months=1,
                instalment_count=3,
            )
            proposer, other = other, proposer

        # One more counter attempt, still with zero rejects anywhere in
        # this test — should be refused AND should cancel, not silently
        # extend the chain further.
        with self.assertRaises(ValueError):
            counter_proposal(
                previous_proposal=current,
                proposed_by=other,
                advance_months=1,
                instalment_count=3,
            )

        self.tenancy.refresh_from_db()
        prop.refresh_from_db()
        self.assertEqual(self.tenancy.status, TenancyStatus.CANCELLED)
        self.assertEqual(prop.status, ListingStatus.ACTIVE)


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
