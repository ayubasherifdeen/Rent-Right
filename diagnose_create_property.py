import os
import uuid

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
import django
django.setup()

from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from apps.accounts.models import Role
from apps.listings.models import PropertyType

User = get_user_model()
email = f'landlord{uuid.uuid4().hex[:8]}@test.com'
u = User.objects.create_user(
    email=email,
    username=f'landlord{uuid.uuid4().hex[:4]}',
    password='testpass123',
    first_name='Test',
    last_name='Landlord',
    phone_number='0244000000',
)
u.userprofile.role = Role.LANDLORD
u.userprofile.save(update_fields=['role'])

client = Client(HTTP_HOST='localhost')
client.force_login(u)

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
    'propertyphoto_set-TOTAL_FORMS': '3',
    'propertyphoto_set-INITIAL_FORMS': '0',
    'propertyphoto_set-MIN_NUM_FORMS': '0',
    'propertyphoto_set-MAX_NUM_FORMS': '10',
}
response = client.post(reverse('listings:create_property'), form_data)
print('status:', response.status_code)
print('redirect:', getattr(response, 'url', None))
print('templates:', [t.name for t in response.templates])
print('context keys:', response.context.keys() if response.context else None)
if response.context:
    form = response.context.get('form')
    fs = response.context.get('photo_formset')
    print('form_errors:', form.errors)
    print('form_non_field:', form.non_field_errors())
    print('photo_errors:', fs.errors)
    print('photo_non_field:', fs.non_form_errors())
    print('form_is_valid:', form.is_valid())
    print('fs_is_valid:', fs.is_valid())
    print('form_fields:', list(form.fields.keys()))
    print('form_data keys:', sorted(form.data.keys()))
text = response.content.decode('utf-8')
for marker in ['This field is required', 'errorlist', 'lease_term_preset', 'lease_term_months', 'Please enter the lease term in months', 'Advance months cannot exceed', 'GHC', 'Publish Now', 'Publish Now →', 'photos-TOTAL_FORMS', 'propertyphoto_set-TOTAL_FORMS']:
    print(marker, marker in text)
for keyword in ['photos-TOTAL_FORMS', 'photos-INITIAL_FORMS', 'photos-MAX_NUM_FORMS', 'propertyphoto_set-TOTAL_FORMS', 'propertyphoto_set-INITIAL_FORMS', 'lease_term_preset', 'lease_term_months']:
    idx = text.find(keyword)
    if idx != -1:
        print('-----', keyword, 'at', idx)
        print(text[idx-120:idx+280])
print('END HTML')
