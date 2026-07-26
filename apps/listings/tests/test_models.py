from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

from apps.listings.models import (
    Property, Amenity, PropertyPhoto,
    PropertyType, ListingStatus, ACT_220_MAX_ADVANCE_MONTHS
)

User = get_user_model()


class AmenityModelTest(TestCase):

    def test_amenity_str(self):
        amenity = Amenity.objects.create(name='WiFi', icon='wifi')
        self.assertEqual(str(amenity), 'WiFi')

    def test_amenity_ordering(self):
        Amenity.objects.create(name='Parking', display_order=2)
        Amenity.objects.create(name='WiFi',    display_order=1)
        names = list(Amenity.objects.values_list('name', flat=True))
        self.assertEqual(names, ['WiFi', 'Parking'])


class PropertyModelTest(TestCase):

    def setUp(self):
        self.landlord = User.objects.create_user(
            email='landlord@test.com',
            username='landlord@test.com',
            password='testpass123',
            first_name='Kwame',
            last_name='Mensah',
            phone_number='0244123456',
        )
        self.base_data = {
            'landlord':      self.landlord,
            'title':         'Test Property',
            'property_type': PropertyType.APARTMENT,
            'bedrooms':      2,
            'bathrooms':     1,
            'address':       '1 Ring Road, East Legon',
            'city':          'Accra',
            'region':        'Greater Accra',
            'monthly_rent':  Decimal('1200.00'),
            'advance_months': 6,
        }

    def _make_property(self, **kwargs):
        data = {**self.base_data, **kwargs}
        return Property(**data)

    # ── Act 220 enforcement ───────────────────────────────────────

    def test_advance_months_at_cap_is_valid(self):
        """Exactly 6 months should pass clean()."""
        prop = self._make_property(advance_months=ACT_220_MAX_ADVANCE_MONTHS)
        prop.full_clean()   # should not raise

    def test_advance_months_over_cap_raises(self):
        """7 months should raise ValidationError."""
        prop = self._make_property(advance_months=7)
        with self.assertRaises(ValidationError) as ctx:
            prop.full_clean()
        self.assertIn('advance_months', ctx.exception.message_dict)
        self.assertIn('(Act 220)', ctx.exception.message_dict['advance_months'][0])

    def test_advance_months_12_raises(self):
        """12 months — common illegal practice in Ghana — must be blocked."""
        prop = self._make_property(advance_months=12)
        with self.assertRaises(ValidationError):
            prop.full_clean()

    # ── Computed properties ───────────────────────────────────────

    def test_advance_amount(self):
        prop = self._make_property(monthly_rent=Decimal('1000.00'), advance_months=6)
        self.assertEqual(prop.advance_amount, Decimal('6000.00'))

    def test_advance_amount_partial_months(self):
        prop = self._make_property(monthly_rent=Decimal('750.00'), advance_months=3)
        self.assertEqual(prop.advance_amount, Decimal('2250.00'))

    def test_act_220_compliant_true_at_max(self):
        prop = self._make_property(advance_months=6)
        self.assertTrue(prop.act_220_compliant)

    def test_is_available_only_when_active(self):
        prop = self._make_property()
        prop.status = ListingStatus.DRAFT
        self.assertFalse(prop.is_available)
        prop.status = ListingStatus.LIVE
        self.assertTrue(prop.is_available)

    # ── GPS validation ────────────────────────────────────────────

    def test_valid_accra_coordinates_pass(self):
        prop = self._make_property(latitude='5.603717', longitude='-0.186964')
        prop.full_clean()   # should not raise

    def test_coordinates_outside_ghana_raise(self):
        prop = self._make_property(latitude='51.5074', longitude='-0.1278')  # London
        with self.assertRaises(ValidationError) as ctx:
            prop.full_clean()
        self.assertIn('latitude', ctx.exception.message_dict)

    # ── get_absolute_url ──────────────────────────────────────────

    def test_get_absolute_url(self):
        prop = self._make_property()
        prop.save()
        url = prop.get_absolute_url()
        self.assertIn(str(prop.pk), url)
        self.assertTrue(url.startswith('/listings/'))

    # ── str ───────────────────────────────────────────────────────

    def test_str(self):
        prop = self._make_property()
        self.assertIn('Test Property', str(prop))


class PropertyPhotoTest(TestCase):

    def setUp(self):
        landlord = User.objects.create_user(
            email='ll@test.com', password='pass', phone_number='0244111111'
        )
        self.property = Property.objects.create(
            landlord=landlord,
            title='Photo Test Property',
            property_type=PropertyType.HOUSE,
            bedrooms=3, bathrooms=2,
            address='5 Cantonments Road',
            city='Accra', region='Greater Accra',
            monthly_rent=Decimal('2000.00'),
            advance_months=6,
        )

    def test_only_one_primary_photo(self):
        """Saving a second photo as primary should demote the first."""
        photo1 = PropertyPhoto.objects.create(
            property=self.property,
            image='listings/test/photo1.jpg',
            is_primary=True
        )
        photo2 = PropertyPhoto.objects.create(
            property=self.property,
            image='listings/test/photo2.jpg',
            is_primary=True
        )
        photo1.refresh_from_db()
        self.assertFalse(photo1.is_primary)
        self.assertTrue(photo2.is_primary)
