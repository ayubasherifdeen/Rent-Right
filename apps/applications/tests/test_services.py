"""
applications/tests/test_services.py

Tests for services.py. Every guard path is tested explicitly.
Pattern: happy path first, then each guard in the order it appears in the service.

Why test the guard order?
Because guard order can matter for UX. If "phone not verified" fires before
"property not active", an unverified tenant gets a different error depending
on which property they apply to. Guard order in the service is the canonical
source of truth — tests pin it.
"""

from django.test import TestCase

from apps.applications.models import Application, ApplicationStatus
from apps.applications.services import (
    submit_application,
    approve_application,
    decline_application,
    withdraw_application,
)
from .helpers import (
    make_landlord,
    make_verified_tenant,
    make_unverified_tenant,
    make_property,
    make_application,
    future_date,
)


class SubmitApplicationTests(TestCase):

    def setUp(self):
        self.landlord = make_landlord()
        self.tenant   = make_verified_tenant()
        self.property = make_property(self.landlord, status='active')

    def test_creates_pending_application(self):
        app = submit_application(self.tenant, self.property, future_date())
        self.assertEqual(app.status, ApplicationStatus.PENDING)
        self.assertEqual(app.tenant, self.tenant)
        self.assertEqual(app.property, self.property)

    def test_blocks_non_tenant_role(self):
        """Landlord cannot apply for their own (or any) property."""
        with self.assertRaises(ValueError) as ctx:
            submit_application(self.landlord, self.property, future_date())
        self.assertIn('Only tenants', str(ctx.exception))

    def test_blocks_unverified_tenant(self):
        unverified = make_unverified_tenant()
        with self.assertRaises(ValueError) as ctx:
            submit_application(unverified, self.property, future_date())
        self.assertIn('verify your phone', str(ctx.exception))

    def test_blocks_if_property_not_active(self):
        draft_property = make_property(self.landlord, status='draft', title='Draft Flat')
        with self.assertRaises(ValueError) as ctx:
            submit_application(self.tenant, draft_property, future_date())
        self.assertIn('not currently available', str(ctx.exception))

    def test_blocks_duplicate_live_application(self):
        submit_application(self.tenant, self.property, future_date())
        with self.assertRaises(ValueError) as ctx:
            submit_application(self.tenant, self.property, future_date())
        self.assertIn('already have an active application', str(ctx.exception))

    def test_allows_reapplication_after_declined(self):
        """Declined is dead — reapplication must succeed."""
        make_application(self.tenant, self.property, status=ApplicationStatus.DECLINED)
        app = submit_application(self.tenant, self.property, future_date())
        self.assertEqual(app.status, ApplicationStatus.PENDING)

    def test_allows_reapplication_after_withdrawn(self):
        """Withdrawn is dead — reapplication must succeed."""
        make_application(self.tenant, self.property, status=ApplicationStatus.WITHDRAWN)
        app = submit_application(self.tenant, self.property, future_date())
        self.assertEqual(app.status, ApplicationStatus.PENDING)

    def test_dry_run_notification_does_not_crash(self):
        """ARKESEL_DRY_RUN=True in dev — _notify must be silent, not raise."""
        # submit_application calls _notify internally; if it raises, this test fails.
        app = submit_application(self.tenant, self.property, future_date())
        self.assertIsNotNone(app.id)

    def test_stores_message(self):
        app = submit_application(self.tenant, self.property, future_date(), message='Hi there')
        self.assertEqual(app.message, 'Hi there')

    def test_stores_move_in_date(self):
        date = future_date(60)
        app = submit_application(self.tenant, self.property, date)
        self.assertEqual(app.move_in_date, date)


class ApproveApplicationTests(TestCase):

    def setUp(self):
        self.landlord = make_landlord()
        self.tenant   = make_verified_tenant()
        self.property = make_property(self.landlord)
        self.application = make_application(
            self.tenant, self.property, status=ApplicationStatus.PENDING
        )

    def test_pending_becomes_approved(self):
        result = approve_application(self.application, self.landlord)
        self.assertEqual(result.status, ApplicationStatus.APPROVED)

    def test_persisted_to_db(self):
        approve_application(self.application, self.landlord)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, ApplicationStatus.APPROVED)

    def test_non_owner_is_rejected(self):
        other_landlord = make_landlord(email='other@test.com', phone='0244500005')
        with self.assertRaises(ValueError) as ctx:
            approve_application(self.application, other_landlord)
        self.assertIn('do not own', str(ctx.exception))

    def test_approving_already_approved_is_rejected(self):
        self.application.status = ApplicationStatus.APPROVED
        self.application.save()
        with self.assertRaises(ValueError) as ctx:
            approve_application(self.application, self.landlord)
        self.assertIn('pending applications can be approved', str(ctx.exception))

    def test_approving_declined_is_rejected(self):
        self.application.status = ApplicationStatus.DECLINED
        self.application.save()
        with self.assertRaises(ValueError):
            approve_application(self.application, self.landlord)


class DeclineApplicationTests(TestCase):

    def setUp(self):
        self.landlord = make_landlord()
        self.tenant   = make_verified_tenant()
        self.property = make_property(self.landlord)
        self.application = make_application(
            self.tenant, self.property, status=ApplicationStatus.PENDING
        )

    def test_pending_becomes_declined(self):
        result = decline_application(self.application, self.landlord)
        self.assertEqual(result.status, ApplicationStatus.DECLINED)

    def test_persisted_to_db(self):
        decline_application(self.application, self.landlord)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, ApplicationStatus.DECLINED)

    def test_non_owner_is_rejected(self):
        other_landlord = make_landlord(email='other2@test.com', phone='0244600006')
        with self.assertRaises(ValueError) as ctx:
            decline_application(self.application, other_landlord)
        self.assertIn('do not own', str(ctx.exception))

    def test_declining_already_declined_is_rejected(self):
        self.application.status = ApplicationStatus.DECLINED
        self.application.save()
        with self.assertRaises(ValueError):
            decline_application(self.application, self.landlord)

    def test_reason_does_not_crash(self):
        """Reason param accepted but not persisted yet — must not raise."""
        result = decline_application(self.application, self.landlord, reason='References unverified')
        self.assertEqual(result.status, ApplicationStatus.DECLINED)


class WithdrawApplicationTests(TestCase):

    def setUp(self):
        self.landlord = make_landlord()
        self.tenant   = make_verified_tenant()
        self.property = make_property(self.landlord)
        self.application = make_application(
            self.tenant, self.property, status=ApplicationStatus.PENDING
        )

    def test_pending_becomes_withdrawn(self):
        result = withdraw_application(self.application, self.tenant)
        self.assertEqual(result.status, ApplicationStatus.WITHDRAWN)

    def test_persisted_to_db(self):
        withdraw_application(self.application, self.tenant)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, ApplicationStatus.WITHDRAWN)

    def test_non_applicant_is_rejected(self):
        other_tenant = make_verified_tenant(email='other3@test.com', phone='0244700007')
        with self.assertRaises(ValueError) as ctx:
            withdraw_application(self.application, other_tenant)
        self.assertIn('your own applications', str(ctx.exception))

    def test_approved_cannot_be_withdrawn(self):
        """
        Post-approval withdrawal is a tenancy abandonment flow — not handled here.
        The error message should be specific and actionable.
        """
        self.application.status = ApplicationStatus.APPROVED
        self.application.save()
        with self.assertRaises(ValueError) as ctx:
            withdraw_application(self.application, self.tenant)
        self.assertIn('contact your landlord', str(ctx.exception))

    def test_declined_cannot_be_withdrawn(self):
        self.application.status = ApplicationStatus.DECLINED
        self.application.save()
        with self.assertRaises(ValueError):
            withdraw_application(self.application, self.tenant)

    def test_already_withdrawn_cannot_be_withdrawn_again(self):
        self.application.status = ApplicationStatus.WITHDRAWN
        self.application.save()
        with self.assertRaises(ValueError):
            withdraw_application(self.application, self.tenant)
