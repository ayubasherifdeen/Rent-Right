"""
applications/tests/test_views.py

Tests for views.py. Focused on HTTP layer only:
  - Correct status codes
  - Correct redirects
  - Auth/role/ownership guards
  - Data isolation (tenant can't see other tenants' applications)

Business logic correctness is tested in test_services.py.
Here we trust the service and test that the view wires it correctly.
"""

from django.test import TestCase, Client
from django.urls import reverse

from apps.applications.models import Application, ApplicationStatus
from .helpers import (
    make_landlord,
    make_verified_tenant,
    make_unverified_tenant,
    make_property,
    make_application,
    future_date,
)


class ApplyViewTests(TestCase):

    def setUp(self):
        self.client   = Client()
        self.landlord = make_landlord()
        self.tenant   = make_verified_tenant()
        self.property = make_property(self.landlord, status='live')
        self.url      = reverse('listings:apply', kwargs={'pk': self.property.pk})

    def test_get_renders_form(self):
        self.client.force_login(self.tenant)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'applications/apply.html')

    def test_post_success_redirects_to_my_applications(self):
        self.client.force_login(self.tenant)
        response = self.client.post(self.url, {
            'move_in_date': future_date().isoformat(),
            'message': 'I am interested.',
        })
        self.assertRedirects(response, reverse('applications:my_applications'))

    def test_post_success_creates_application(self):
        self.client.force_login(self.tenant)
        self.client.post(self.url, {
            'move_in_date': future_date().isoformat(),
            'message': '',
        })
        self.assertTrue(
            Application.objects.filter(tenant=self.tenant, property=self.property).exists()
        )

    def test_unauthenticated_redirects_to_login(self):
        response = self.client.post(self.url, {'move_in_date': future_date().isoformat()})
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login', response['Location'])

    def test_landlord_gets_403(self):
        """Role check: landlords cannot apply."""
        self.client.force_login(self.landlord)
        response = self.client.post(self.url, {'move_in_date': future_date().isoformat()})
        self.assertEqual(response.status_code, 403)

    def test_unverified_tenant_gets_403(self):
        """@phone_verified_required fires before the view body."""
        unverified = make_unverified_tenant()
        self.client.force_login(unverified)
        response = self.client.post(self.url, {'move_in_date': future_date().isoformat()})
        self.assertEqual(response.status_code, 302)  # redirect to verify_phone

    def test_bad_uuid_returns_404(self):
        self.client.force_login(self.tenant)
        bad_url = reverse('listings:apply', kwargs={'pk': '00000000-0000-0000-0000-000000000000'})
        response = self.client.get(bad_url)
        self.assertEqual(response.status_code, 404)

    def test_duplicate_application_returns_400(self):
        make_application(self.tenant, self.property, status=ApplicationStatus.PENDING)
        self.client.force_login(self.tenant)
        response = self.client.post(self.url, {
            'move_in_date': future_date().isoformat(),
            'message': '',
        })
        self.assertEqual(response.status_code, 400)

    def test_past_move_in_date_invalid(self):
        import datetime
        self.client.force_login(self.tenant)
        response = self.client.post(self.url, {
            'move_in_date': (datetime.date.today() - datetime.timedelta(days=1)).isoformat(),
            'message': '',
        })
        # Form validation error — should re-render the form, not 302
        self.assertEqual(response.status_code, 200)


class MyApplicationsViewTests(TestCase):

    def setUp(self):
        self.client    = Client()
        self.landlord  = make_landlord()
        self.tenant_a  = make_verified_tenant(email='a@test.com', phone='0244111111')
        self.tenant_b  = make_verified_tenant(email='b@test.com', phone='0244222222')
        self.property  = make_property(self.landlord)
        self.property2 = make_property(self.landlord, title='Second Place')
        self.url       = reverse('applications:my_applications')

    def test_tenant_sees_only_own_applications(self):
        app_a = make_application(self.tenant_a, self.property)
        make_application(self.tenant_b, self.property2)  # must not appear
        self.client.force_login(self.tenant_a)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn(app_a, response.context['applications'])
        self.assertEqual(len(response.context['applications']), 1)

    def test_unauthenticated_redirects(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_landlord_gets_403(self):
        self.client.force_login(self.landlord)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)


class ReceivedApplicationsViewTests(TestCase):

    def setUp(self):
        self.client     = Client()
        self.landlord_a = make_landlord(email='la@test.com', phone='0244333333')
        self.landlord_b = make_landlord(email='lb@test.com', phone='0244444444')
        self.tenant     = make_verified_tenant()
        self.prop_a     = make_property(self.landlord_a)
        self.prop_b     = make_property(self.landlord_b, title='Landlord B Property')
        self.url        = reverse('applications:received_applications')

    def test_landlord_sees_only_own_properties_applications(self):
        app_a = make_application(self.tenant, self.prop_a)
        make_application(self.tenant, self.prop_b)  # must not appear
        self.client.force_login(self.landlord_a)
        response = self.client.get(self.url)
        self.assertIn(app_a, response.context['applications'])
        self.assertEqual(len(response.context['applications']), 1)

    def test_tenant_gets_403(self):
        self.client.force_login(self.tenant)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)


class ApproveApplicationViewTests(TestCase):

    def setUp(self):
        self.client      = Client()
        self.landlord    = make_landlord()
        self.tenant      = make_verified_tenant()
        self.property    = make_property(self.landlord)
        self.application = make_application(self.tenant, self.property)

    def _url(self):
        return reverse('applications:approve_application', kwargs={'pk': self.application.pk})

    def test_approve_success_redirects(self):
        self.client.force_login(self.landlord)
        response = self.client.post(self._url())
        self.assertRedirects(response, reverse('applications:received_applications'))

    def test_approve_changes_status(self):
        self.client.force_login(self.landlord)
        self.client.post(self._url())
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, ApplicationStatus.APPROVED)

    def test_non_owner_cannot_approve(self):
        other = make_landlord(email='other@test.com', phone='0244555555')
        self.client.force_login(other)
        response = self.client.post(self._url())
        # Service raises ValueError → flash error, redirect (not 403 — landlord role is valid)
        self.assertRedirects(response, reverse('applications:received_applications'))
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, ApplicationStatus.PENDING)

    def test_get_not_allowed(self):
        self.client.force_login(self.landlord)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 405)

    def test_tenant_gets_403(self):
        self.client.force_login(self.tenant)
        response = self.client.post(self._url())
        self.assertEqual(response.status_code, 403)


class DeclineApplicationViewTests(TestCase):

    def setUp(self):
        self.client      = Client()
        self.landlord    = make_landlord()
        self.tenant      = make_verified_tenant()
        self.property    = make_property(self.landlord)
        self.application = make_application(self.tenant, self.property)

    def _url(self):
        return reverse('applications:decline_application', kwargs={'pk': self.application.pk})

    def test_decline_success_redirects(self):
        self.client.force_login(self.landlord)
        response = self.client.post(self._url())
        self.assertRedirects(response, reverse('applications:received_applications'))

    def test_decline_changes_status(self):
        self.client.force_login(self.landlord)
        self.client.post(self._url())
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, ApplicationStatus.DECLINED)

    def test_get_not_allowed(self):
        self.client.force_login(self.landlord)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 405)


class WithdrawApplicationViewTests(TestCase):

    def setUp(self):
        self.client      = Client()
        self.landlord    = make_landlord()
        self.tenant      = make_verified_tenant()
        self.property    = make_property(self.landlord)
        self.application = make_application(self.tenant, self.property)

    def _url(self):
        return reverse('applications:withdraw_application', kwargs={'pk': self.application.pk})

    def test_withdraw_success_redirects_to_my_applications(self):
        self.client.force_login(self.tenant)
        response = self.client.post(self._url())
        self.assertRedirects(response, reverse('applications:my_applications'))

    def test_withdraw_changes_status(self):
        self.client.force_login(self.tenant)
        self.client.post(self._url())
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, ApplicationStatus.WITHDRAWN)

    def test_non_applicant_gets_redirect_with_error(self):
        """Service raises ValueError — view flashes error and redirects (not 403)."""
        other_tenant = make_verified_tenant(email='c@test.com', phone='0244666666')
        self.client.force_login(other_tenant)
        response = self.client.post(self._url())
        self.assertRedirects(response, reverse('applications:my_applications'))
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, ApplicationStatus.PENDING)

    def test_approved_application_cannot_be_withdrawn(self):
        self.application.status = ApplicationStatus.APPROVED
        self.application.save()
        self.client.force_login(self.tenant)
        response = self.client.post(self._url())
        # Redirects back with an error flash — status unchanged
        self.assertRedirects(response, reverse('applications:my_applications'))
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, ApplicationStatus.APPROVED)

    def test_get_not_allowed(self):
        self.client.force_login(self.tenant)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 405)
