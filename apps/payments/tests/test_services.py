"""
All Paystack HTTP calls are mocked (patched at apps.payments.services.requests)
— there's no live Paystack account to test against this session. These tests
verify RentRight's own guard logic, state transitions, and idempotency; they
do NOT verify that the mocked request/response shapes exactly match Paystack's
real API. Re-run against Paystack's test keys before trusting this in
production — see handoff v12.
"""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from apps.payments import services
from apps.payments.models import Payment, PaymentStatus, PaymentType

from apps.payments.tests.helpers import make_active_tenancy_with_schedule, make_pending_payment_tenancy


@override_settings(PAYSTACK_SECRET_KEY="sk_test_dummy")
class InitiatePaymentTests(TestCase):
    def setUp(self):
        self.tenancy = make_pending_payment_tenancy()

    @patch("apps.payments.services.requests.post")
    def test_move_in_payment_creates_pending_row_and_returns_url(self, mock_post):
        mock_post.return_value = MagicMock(
            ok=True,
            json=lambda: {
                "status": True,
                "data": {"authorization_url": "https://paystack.test/pay/abc", "reference": "x"},
            },
        )
        payment, url = services.initiate_payment(
            self.tenancy, self.tenancy.tenant, PaymentType.MOVE_IN, "https://app.test/callback/"
        )
        self.assertEqual(payment.status, PaymentStatus.PENDING)
        self.assertEqual(url, "https://paystack.test/pay/abc")

    def test_non_tenant_cannot_initiate(self):
        with self.assertRaises(ValueError):
            services.initiate_payment(
                self.tenancy, self.tenancy.landlord, PaymentType.MOVE_IN, "https://app.test/callback/"
            )

    def test_move_in_blocked_when_not_pending_payment(self):
        self.tenancy.status = "active"
        self.tenancy.save(update_fields=["status"])
        with self.assertRaises(ValueError):
            services.initiate_payment(
                self.tenancy, self.tenancy.tenant, PaymentType.MOVE_IN, "https://app.test/callback/"
            )

    def test_move_in_blocked_if_already_paid(self):
        Payment.objects.create(
            tenancy=self.tenancy,
            paid_by=self.tenancy.tenant,
            payment_type=PaymentType.MOVE_IN,
            status=PaymentStatus.SUCCESS,
            amount=self.tenancy.advance_amount,
            reference="already-paid",
        )
        with self.assertRaises(ValueError):
            services.initiate_payment(
                self.tenancy, self.tenancy.tenant, PaymentType.MOVE_IN, "https://app.test/callback/"
            )

    @patch("apps.payments.services.requests.post")
    def test_paystack_failure_marks_row_failed_and_reraises(self, mock_post):
        mock_post.return_value = MagicMock(
            ok=False, json=lambda: {"status": False, "message": "bad request"}
        )
        with self.assertRaises(services.PaystackError):
            services.initiate_payment(
                self.tenancy, self.tenancy.tenant, PaymentType.MOVE_IN, "https://app.test/callback/"
            )
        payment = Payment.objects.get(tenancy=self.tenancy)
        self.assertEqual(payment.status, PaymentStatus.FAILED)

    def test_missing_secret_key_raises_loudly(self):
        with override_settings(PAYSTACK_SECRET_KEY=""):
            with self.assertRaises(services.PaystackError):
                services.initiate_payment(
                    self.tenancy,
                    self.tenancy.tenant,
                    PaymentType.MOVE_IN,
                    "https://app.test/callback/",
                )


@override_settings(PAYSTACK_SECRET_KEY="sk_test_dummy")
class InstalmentPaymentTests(TestCase):
    def setUp(self):
        self.tenancy, self.schedule = make_active_tenancy_with_schedule()

    @patch("apps.payments.services.requests.post")
    def test_instalment_payment_matches_schedule_entry(self, mock_post):
        mock_post.return_value = MagicMock(
            ok=True,
            json=lambda: {
                "status": True,
                "data": {"authorization_url": "https://paystack.test/pay/abc", "reference": "x"},
            },
        )
        due_date = self.schedule[0]["due_date"]
        payment, _ = services.initiate_payment(
            self.tenancy,
            self.tenancy.tenant,
            PaymentType.INSTALMENT,
            "https://app.test/callback/",
            instalment_due_date=due_date,
        )
        self.assertEqual(str(payment.amount), str(self.schedule[0]["amount"]))

    def test_unmatched_due_date_rejected(self):
        with self.assertRaises(ValueError):
            services.initiate_payment(
                self.tenancy,
                self.tenancy.tenant,
                PaymentType.INSTALMENT,
                "https://app.test/callback/",
                instalment_due_date="1999-01-01",
            )

    def test_instalment_blocked_before_tenancy_active(self):
        self.tenancy.status = "pending_payment"
        self.tenancy.save(update_fields=["status"])
        with self.assertRaises(ValueError):
            services.initiate_payment(
                self.tenancy,
                self.tenancy.tenant,
                PaymentType.INSTALMENT,
                "https://app.test/callback/",
                instalment_due_date=self.schedule[0]["due_date"],
            )


@override_settings(PAYSTACK_SECRET_KEY="sk_test_dummy")
class VerifyAndRecordPaymentTests(TestCase):
    def setUp(self):
        self.tenancy = make_pending_payment_tenancy()
        self.payment = Payment.objects.create(
            tenancy=self.tenancy,
            paid_by=self.tenancy.tenant,
            payment_type=PaymentType.MOVE_IN,
            status=PaymentStatus.PENDING,
            amount=self.tenancy.advance_amount,
            reference="ref-123",
        )

    @patch("apps.payments.services.generate_payment_receipt")
    @patch("apps.payments.services.activate_tenancy")
    @patch("apps.payments.services.requests.get")
    def test_successful_verify_activates_tenancy_and_generates_receipt(
        self, mock_get, mock_activate, mock_receipt
    ):
        mock_get.return_value = MagicMock(
            ok=True,
            json=lambda: {
                "status": True,
                "data": {
                    "status": "success",
                    "id": 999,
                    "channel": "mobile_money",
                    "paid_at": "2026-07-22T10:00:00Z",
                },
            },
        )
        payment = services.verify_and_record_payment("ref-123")
        self.assertEqual(payment.status, PaymentStatus.SUCCESS)
        mock_activate.assert_called_once()
        mock_receipt.assert_called_once()

    @patch("apps.payments.services.requests.get")
    def test_idempotent_on_already_successful_payment(self, mock_get):
        self.payment.status = PaymentStatus.SUCCESS
        self.payment.save(update_fields=["status"])
        result = services.verify_and_record_payment("ref-123")
        self.assertEqual(result.pk, self.payment.pk)
        mock_get.assert_not_called()

    @patch("apps.payments.services.requests.get")
    def test_failed_paystack_status_marks_payment_failed(self, mock_get):
        mock_get.return_value = MagicMock(
            ok=True, json=lambda: {"status": True, "data": {"status": "failed"}}
        )
        payment = services.verify_and_record_payment("ref-123")
        self.assertEqual(payment.status, PaymentStatus.FAILED)

    def test_unknown_reference_raises(self):
        with self.assertRaises(ValueError):
            services.verify_and_record_payment("does-not-exist")


class WebhookSignatureTests(TestCase):
    @override_settings(PAYSTACK_SECRET_KEY="sk_test_dummy")
    def test_valid_signature_accepted(self):
        import hashlib
        import hmac

        body = b'{"event": "charge.success"}'
        sig = hmac.new(b"sk_test_dummy", body, hashlib.sha512).hexdigest()
        self.assertTrue(services.verify_webhook_signature(body, sig))

    @override_settings(PAYSTACK_SECRET_KEY="sk_test_dummy")
    def test_invalid_signature_rejected(self):
        body = b'{"event": "charge.success"}'
        self.assertFalse(services.verify_webhook_signature(body, "not-the-right-signature"))


class OverdueInstalmentTests(TestCase):
    def test_overdue_rows_flagged(self):
        tenancy, schedule = make_active_tenancy_with_schedule(
            first_due_offset_days=-10  # already past due, unpaid
        )
        overdue = services.get_overdue_instalments(tenancy)
        self.assertEqual(len(overdue), 1)
        self.assertEqual(overdue[0]["status"], "overdue")
