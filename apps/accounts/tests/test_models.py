from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import OTP, Role, User, UserProfile


class UserModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='ama@example.com',
            username='ama',
            password='testpass123',
            first_name='Ama',
            last_name='Owusu',
            phone_number='0241234567',
        )

    def test_full_name_returns_first_and_last(self):
        self.assertEqual(self.user.full_name, 'Ama Owusu')

    def test_full_name_fallback_to_email(self):
        self.user.first_name = ''
        self.user.last_name = ''
        self.assertEqual(self.user.full_name, 'ama@example.com')

    def test_signal_creates_profile_on_user_creation(self):
        self.assertTrue(hasattr(self.user, 'userprofile'))
        self.assertIsInstance(self.user.userprofile, UserProfile)

    def test_default_role_is_tenant(self):
        self.assertEqual(self.user.role, Role.TENANT)

    def test_is_tenant_helper(self):
        self.user.userprofile.role = Role.TENANT
        self.user.userprofile.save()
        self.assertTrue(self.user.is_tenant())

    def test_is_landlord_helper(self):
        self.user.userprofile.role = Role.LANDLORD
        self.user.userprofile.save()
        self.assertTrue(self.user.is_landlord())
        self.assertFalse(self.user.is_tenant())

    def test_email_is_username_field(self):
        self.assertEqual(User.USERNAME_FIELD, 'email')


class OTPModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='kwame@example.com',
            username='kwame',
            password='testpass123',
        )

    def test_otp_is_valid_before_expiry(self):
        otp = OTP.objects.create(
            user=self.user,
            code='123456',
            purpose='phone_verify',
            expires_at=timezone.now() + timezone.timedelta(minutes=10),
        )
        self.assertTrue(otp.is_valid)

    def test_otp_invalid_after_expiry(self):
        otp = OTP.objects.create(
            user=self.user,
            code='123456',
            purpose='phone_verify',
            expires_at=timezone.now() - timezone.timedelta(minutes=1),
        )
        self.assertFalse(otp.is_valid)

    def test_otp_invalid_after_consume(self):
        otp = OTP.objects.create(
            user=self.user,
            code='123456',
            purpose='phone_verify',
            expires_at=timezone.now() + timezone.timedelta(minutes=10),
        )
        otp.consume()
        self.assertFalse(otp.is_valid)

