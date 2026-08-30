"""
apps/notifications/services.py

The one function every other app's _notify() stub (or, for accounts'
OTP functions, the function itself) calls into. This function never
raises — a failed SMS must never roll back a real transaction (payment
recorded, agreement executed, maintenance resolved).

"""

import logging

import requests
from django.conf import settings

from .models import Notification, NotificationPurpose, NotificationStatus

logger = logging.getLogger(__name__)

ARKESEL_SEND_URL = "https://sms.arkesel.com/api/v2/sms/send"


def _normalize_phone(phone: str) -> str:
    """
    normalize number since Arkesel expects a Ghanaian phone number in international format,
    +233501234567. Accepts a local number (0501234567) or an international
    number with or without the leading + (233501234567 or +233501234567).
    """
    phone = (phone or "").strip().replace(" ", "")
    if phone.startswith("+"):
        return phone
    if phone.startswith("0"):
        return "+233" + phone[1:]
    if phone.startswith("233"):
        return "+" + phone
    raise ValueError(f"Invalid Ghanaian phone number: {phone}")


def notify_user(user, message, purpose=NotificationPurpose.GENERAL):
    """
    Send `message` to `user` via SMS and log the attempt. 
    """
    log = Notification.objects.create(
        user=user, purpose=purpose, message=message, status=NotificationStatus.PENDING
    )

    phone = getattr(user, "phone_number", None)
    if not phone:
        log.status = NotificationStatus.FAILED
        log.error = "User has no phone number on file."
        log.save(update_fields=["status", "error"])
        logger.warning(f"[NOTIFICATIONS] No phone number for user {user.id}, purpose={purpose}")
        return log

    try:
        phone = _normalize_phone(phone)
    except ValueError as e:
        log.status = NotificationStatus.FAILED
        log.error = str(e)[:500]
        log.save(update_fields=["status", "error"])
        logger.warning(f"[NOTIFICATIONS] {e} (user={user.id}, purpose={purpose})")
        return log

    if getattr(settings, "ARKESEL_DRY_RUN", True):
        logger.debug(f"[NOTIFICATIONS][SMS DRY RUN] to={user} ({phone}): {message}")
        log.status = NotificationStatus.DRY_RUN
        log.save(update_fields=["status"])
        return log

    try:
        response = requests.post(
            ARKESEL_SEND_URL,
            headers={
                "api-key": settings.ARKESEL_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "sender": settings.ARKESEL_SENDER_ID,
                "message": message,
                "recipients": [phone],
            },
            timeout=10,
        )
        data = response.json()
        if response.status_code == 200 and data.get("status") == "success":
            log.status = NotificationStatus.SENT
            log.provider_message_id = data.get("data", {}).get("id", "")
        else:
            log.status = NotificationStatus.FAILED
            log.error = str(data)[:500]
    except Exception as e:
        logger.exception(f"[NOTIFICATIONS] Arkesel send failed for user {user.id}")
        log.status = NotificationStatus.FAILED
        log.error = str(e)[:500]

    log.save(update_fields=["status", "error", "provider_message_id"])
    return log
