from decimal import Decimal
from django.test import TestCase
from apps.listings.forms import PropertyForm
from apps.listings.models import ACT_220_MAX_ADVANCE_MONTHS


class PropertyFormAct220Test(TestCase):
    """
    The form is the user-facing Act 220 enforcement layer.
    These tests verify that no illegal value can be submitted through the UI.
    """

    def _base_data(self, **overrides):
        data = {
            'title':            'Test Apartment',
            'property_type':    'apartment',
            'furnishing_status': 'unfurnished',
            'bedrooms':         2,
            'bathrooms':        1,
            'address':          '1 Ring Road East',
            'city':             'Accra',
            'region':           'Greater Accra',
            'monthly_rent':     '1200.00',
            'payment_cycle':    'annual',
            'advance_months':   6,
            'security_deposit': '0',
        }
        data.update(overrides)
        return data

    def test_valid_form_at_cap(self):
        form = PropertyForm(data=self._base_data(advance_months=6))
        self.assertTrue(form.is_valid(), form.errors)

    def test_valid_form_below_cap(self):
        form = PropertyForm(data=self._base_data(advance_months=3))
        self.assertTrue(form.is_valid(), form.errors)

    def test_advance_months_7_invalid(self):
        form = PropertyForm(data=self._base_data(advance_months=7))
        self.assertFalse(form.is_valid())
        self.assertIn('advance_months', form.errors)
        self.assertIn('Act 220', form.errors['advance_months'][0])

    def test_advance_months_12_invalid(self):
        """Simulates the most common illegal practice in Ghana."""
        form = PropertyForm(data=self._base_data(advance_months=12))
        self.assertFalse(form.is_valid())
        self.assertIn('advance_months', form.errors)

    def test_advance_months_zero_invalid(self):
        form = PropertyForm(data=self._base_data(advance_months=0))
        self.assertFalse(form.is_valid())
        self.assertIn('advance_months', form.errors)

    def test_only_latitude_without_longitude_invalid(self):
        """GPS must be both or neither."""
        form = PropertyForm(data=self._base_data(latitude='5.6037', longitude=''))
        self.assertFalse(form.is_valid())

    def test_both_gps_coordinates_valid(self):
        form = PropertyForm(data=self._base_data(latitude='5.6037', longitude='-0.1870'))
        self.assertTrue(form.is_valid(), form.errors)

    def test_no_gps_is_valid(self):
        """GPS is optional — no coordinates should still be valid."""
        form = PropertyForm(data=self._base_data(latitude='', longitude=''))
        self.assertTrue(form.is_valid(), form.errors)
