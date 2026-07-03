"""
applications/tests/test_models.py

Tests for Application model.
Three things to verify:
  1. UUID primary key is auto-assigned.
  2. __str__ is readable and contains the right information.
  3. The conditional uniqueness constraint enforces the right business rule —
     one live application per tenant per property, but reapplication is allowed
     after withdrawal or decline.
"""

from django.test import TestCase
from django.db import IntegrityError

from apps.applications.models import Application, ApplicationStatus
from .helpers import make_landlord, make_verified_tenant, make_property, make_application, future_date


class ApplicationUUIDTests(TestCase):

    def setUp(self):
        self.landlord = make_landlord()
        self.tenant   = make_verified_tenant()
        self.property = make_property(self.landlord)

    def test_uuid_primary_key_is_auto_assigned(self):
        app = make_application(self.tenant, self.property)
        self.assertIsNotNone(app.id)
        self.assertEqual(len(str(app.id)), 36)  # UUID4 string format


class ApplicationStrTests(TestCase):

    def setUp(self):
        self.landlord = make_landlord()
        self.tenant   = make_verified_tenant()
        self.property = make_property(self.landlord)

    def test_str_contains_tenant_name(self):
        app = make_application(self.tenant, self.property)
        self.assertIn('Ama Asante', str(app))

    def test_str_contains_property_title(self):
        app = make_application(self.tenant, self.property)
        self.assertIn('Test Apartment', str(app))

    def test_str_contains_status(self):
        app = make_application(self.tenant, self.property)
        self.assertIn('pending', str(app))


class ApplicationConditionalConstraintTests(TestCase):
    """
    The UniqueConstraint only fires for status IN ('pending', 'approved').
    Withdrawn and declined applications are dead — reapply is allowed.
    """

    def setUp(self):
        self.landlord = make_landlord()
        self.tenant   = make_verified_tenant()
        self.property = make_property(self.landlord)

    def test_second_pending_application_is_rejected(self):
        make_application(self.tenant, self.property, status=ApplicationStatus.PENDING)
        with self.assertRaises(IntegrityError):
            make_application(self.tenant, self.property, status=ApplicationStatus.PENDING)

    def test_second_application_after_withdrawn_is_allowed(self):
        """Withdrawn = dead. Constraint should not fire."""
        make_application(self.tenant, self.property, status=ApplicationStatus.WITHDRAWN)
        # This must not raise
        app2 = make_application(self.tenant, self.property, status=ApplicationStatus.PENDING)
        self.assertEqual(app2.status, ApplicationStatus.PENDING)

    def test_second_application_after_declined_is_allowed(self):
        """Declined = dead. Constraint should not fire."""
        make_application(self.tenant, self.property, status=ApplicationStatus.DECLINED)
        app2 = make_application(self.tenant, self.property, status=ApplicationStatus.PENDING)
        self.assertEqual(app2.status, ApplicationStatus.PENDING)

    def test_approved_application_blocks_second_pending(self):
        """Approved is still 'live' — second PENDING must be rejected."""
        make_application(self.tenant, self.property, status=ApplicationStatus.APPROVED)
        with self.assertRaises(IntegrityError):
            make_application(self.tenant, self.property, status=ApplicationStatus.PENDING)


class ApplicationPredicateTests(TestCase):

    def setUp(self):
        self.landlord = make_landlord()
        self.tenant   = make_verified_tenant()
        self.property = make_property(self.landlord)

    def test_is_pending(self):
        app = make_application(self.tenant, self.property, status=ApplicationStatus.PENDING)
        self.assertTrue(app.is_pending)
        self.assertFalse(app.is_approved)

    def test_is_approved(self):
        app = make_application(self.tenant, self.property, status=ApplicationStatus.APPROVED)
        self.assertTrue(app.is_approved)
        self.assertFalse(app.is_pending)

    def test_is_declined(self):
        app = make_application(self.tenant, self.property, status=ApplicationStatus.DECLINED)
        self.assertTrue(app.is_declined)

    def test_is_withdrawn(self):
        app = make_application(self.tenant, self.property, status=ApplicationStatus.WITHDRAWN)
        self.assertTrue(app.is_withdrawn)
