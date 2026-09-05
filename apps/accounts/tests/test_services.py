from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import OTP, Role, User
from apps.accounts.services import (
    confirm_phone_verification,
    create_otp,
    register_user,
    reset_password,
    send_password_reset_otp,
    verify_otp,
)


class RegisterUserServiceTests(TestCase):
    def test_creates_user_with_correct_role(self):
        user = register_user(
            email='kofi@example.com',
            password='secure123',
            first_name='Kofi',
            last_name='Mensah',
            phone_number='0551234567',
            role=Role.LANDLORD,
        )
        self.assertEqual(user.role, Role.LANDLORD)
        self.assertEqual(user.email, 'kofi@example.com')

    def test_raises_on_invalid_role(self):
        with self.assertRaises(ValueError):
            register_user(
                email='bad@example.com',
                password='secure123',
                first_name='Bad',
                last_name='Role',
                phone_number='0551234567',
                role='overlord',
            )

    def test_user_not_verified_on_creation(self):
        user = register_user(
            email='akua@example.com',
            password='secure123',
            first_name='Akua',
            last_name='Asante',
            phone_number='0551234567',
            role=Role.TENANT,
        )
        self.assertFalse(user.is_verified)


class OTPServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='yaw@example.com',
            username='yaw',
            password='testpass123',
            phone_number='0241234567',
        )

    def test_verify_otp_returns_true_on_valid_code(self):
        otp = create_otp(self.user, 'phone_verify')
        result = verify_otp(self.user, otp.code, 'phone_verify')
        self.assertEqual(result, str(otp.id))

    def test_verify_otp_consumes_the_otp(self):
        otp = create_otp(self.user, 'phone_verify')
        verify_otp(self.user, otp.code, 'phone_verify')
        otp.refresh_from_db()
        self.assertTrue(otp.is_used)

    def test_verify_otp_returns_false_on_wrong_code(self):
        create_otp(self.user, 'phone_verify')
        result = verify_otp(self.user, '000000', 'phone_verify')
        self.assertFalse(result)

    def test_create_otp_invalidates_previous_otp(self):
        otp1 = create_otp(self.user, 'phone_verify')
        create_otp(self.user, 'phone_verify')  # second OTP
        otp1.refresh_from_db()
        self.assertTrue(otp1.is_used)

    def test_confirm_phone_sets_user_verified(self):
        otp = create_otp(self.user, 'phone_verify')
        result = confirm_phone_verification(self.user, otp.code)
        self.assertTrue(result)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_verified)

    def test_password_reset_otp_by_email(self):
        otp = send_password_reset_otp(self.user.phone_number)
        self.assertIsNotNone(otp)
        self.assertEqual(otp.purpose, 'password_reset')

    def test_password_reset_returns_none_for_unknown_email(self):
        result = send_password_reset_otp('nobody@example.com')
        self.assertIsNone(result)

    def test_reset_password_updates_password(self):
        otp = create_otp(self.user, 'password_reset')
        success = reset_password(self.user, otp.code, 'newpassword456')
        self.assertTrue(success)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('newpassword456'))


class ViewTests(TestCase):
    def test_register_page_loads(self):
        response = self.client.get('/accounts/register/')
        self.assertEqual(response.status_code, 200)

    def test_login_page_loads(self):
        response = self.client.get('/accounts/login/')
        self.assertEqual(response.status_code, 200)

    def test_dashboard_redirects_unauthenticated(self):
        response = self.client.get('/accounts/dashboard/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])

    def test_register_creates_user_and_redirects(self):
        response = self.client.post('/accounts/register/', {
            'first_name': 'Abena',
            'last_name': 'Boateng',
            'email': 'abena@example.com',
            'phone_number': '0241234567',
            'role': 'tenant',
            'password1': 'strongpass99',
            'password2': 'strongpass99',
        })
        self.assertRedirects(response, '/accounts/verify-phone/')
        self.assertTrue(User.objects.filter(email='abena@example.com').exists())

