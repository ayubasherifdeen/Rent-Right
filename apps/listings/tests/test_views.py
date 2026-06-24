from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role
from apps.listings.models import Property, PropertyType, ListingStatus

User = get_user_model()


class PropertyCreatePublishViewTests(TestCase):
    def setUp(self):
        self.landlord = User.objects.create_user(
            email='landlord@test.com',
            username='landlord',
            password='testpass123',
            first_name='Test',
            last_name='Landlord',
            phone_number='0244000000',
        )
        self.landlord.userprofile.role = Role.LANDLORD
        self.landlord.userprofile.save(update_fields=['role'])
        self.create_url = reverse('listings:create_property')

    def test_create_property_redirects_to_publish_prompt(self):
        form_data = {
            'title': 'Draft Property',
            'property_type': PropertyType.APARTMENT,
            'furnishing_status': 'unfurnished',
            'bedrooms': 2,
            'bathrooms': 1,
            'address': '123 Main St',
            'city': 'Accra',
            'region': 'Greater Accra',
            'monthly_rent': '1200.00',
            'payment_cycle': 'annual',
            'advance_months': 6,
            'security_deposit': '0',
            'lease_term_preset': '12',
            'lease_term_months': '12',
            'lease_term_months_custom': '',
            'available_from': '',
            'latitude': '',
            'longitude': '',
            'amenities': [],
            'photos-TOTAL_FORMS': '3',
            'photos-INITIAL_FORMS': '0',
            'photos-MIN_NUM_FORMS': '0',
            'photos-MAX_NUM_FORMS': '10',
        }

        self.client.force_login(self.landlord)
        response = self.client.post(self.create_url, data=form_data)

        self.assertEqual(response.status_code, 302)
        property_obj = Property.objects.first()
        self.assertIsNotNone(property_obj)
        self.assertRedirects(response, reverse('listings:publish_prompt', kwargs={'pk': property_obj.pk}))
        self.assertEqual(property_obj.status, ListingStatus.DRAFT)
        self.assertEqual(property_obj.landlord, self.landlord)

    def test_publish_prompt_post_publishes_listing(self):
        property_obj = Property.objects.create(
            landlord=self.landlord,
            title='Draft Property',
            property_type=PropertyType.APARTMENT,
            bedrooms=1,
            bathrooms=1,
            address='1 Road',
            city='Accra',
            region='Greater Accra',
            monthly_rent=Decimal('500.00'),
            advance_months=6,
        )

        publish_url = reverse('listings:publish_prompt', kwargs={'pk': property_obj.pk})
        self.client.force_login(self.landlord)
        response = self.client.post(publish_url)

        property_obj.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('listings:property_detail', kwargs={'pk': property_obj.pk}))
        self.assertEqual(property_obj.status, ListingStatus.ACTIVE)

    def test_create_property_requires_login(self):
        response = self.client.get(self.create_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])
