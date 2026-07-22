"""
All business logic for the accounts domain.

Views call these functions. This keeps views thin and makes every
critical operation independently testable.
"""
import random
import string
from datetime import timedelta

from django.contrib.auth import authenticate
from django.db import transaction
from django.utils import timezone

from .models import OTP, Role, User, UserProfile

import logging

logger = logging.getLogger(__name__)


# ─── OTP ──────────────────────────────────────────────────────────────────────

OTP_EXPIRY_MINUTES = 10


def generate_otp_code(length=6):
    """Return a random numeric OTP string."""
    return ''.join(random.choices(string.digits, k=length))


def create_otp(user: User, purpose: str) -> OTP:
    """
    Invalidate any existing unused OTPs for this user + purpose,
    then create a fresh one.
    """
    OTP.objects.filter(user=user, purpose=purpose, is_used=False).update(is_used=True)

    return OTP.objects.create(
        user=user,
        code=generate_otp_code(),
        purpose=purpose,
        expires_at=timezone.now() + timedelta(minutes=OTP_EXPIRY_MINUTES),
    )


def verify_otp(user: User, code: str, purpose: str) -> bool:
    """
    Validate OTP. Returns True and consumes the OTP on success.
    Returns False if code is wrong, expired, or already used.
    """
    try:
        otp = OTP.objects.get(
            user=user,
            code=code,
            purpose=purpose,
            is_used=False,
        )
    except OTP.DoesNotExist:
        return False

    if not otp.is_valid:
        return False

    with transaction.atomic():
        otp.consume()

    return True

def _unique_username(base: str) -> str:
    """Append a number suffix until the username is unique."""
    username = base
    counter = 1
    while User.objects.filter(username=username).exists():
        username = f"{base}{counter}"
        counter += 1
    return username

# Registration

@transaction.atomic
def register_user(
    email: str,
    password: str,
    first_name: str,
    last_name: str,
    phone_number: str,
    role: str,
) -> User:
    """
    Create a User + UserProfile in one atomic block.
    Raises ValueError if role is invalid
    Raises IntegrityError if email already exists (let the view handle it).
    """
    if role not in Role.values:
        raise ValueError(f"Invalid role: {role}")

    # Derive a username from email to satisfy AbstractUser
    base_username = email.split('@')[0]
    username = _unique_username(base_username)

    user = User.objects.create_user(
        email=email,
        username=username,
        password=password,
        first_name=first_name,
        last_name=last_name,
        phone_number=phone_number,
        is_active=True,
        is_verified=False, # because phone verification otp not verified yet
    )

    # Signal auto-creates UserProfile; we just update the role
    user.userprofile.role = role
    user.userprofile.save(update_fields=['role'])

    return user

# Phone Verification

def send_phone_verification_otp(user: User) -> OTP:
    """
    Create a phone-verification OTP and send it via Arkesel SMS.
    The actual SMS sending is done by the notifications app to keep
    this service free of external dependencies.
    Returns the OTP so the caller can trigger the SMS task.
    """
    otp =  create_otp(user, purpose='phone_verify')
    logger.debug(f"[DEV] Phone verify OTP for {user.phone_number}: {otp.code}")
    return otp


def confirm_phone_verification(user: User, code: str) -> bool:
    """
    Verify the phone OTP. If valid, mark the user as verified.
    """
    success = verify_otp(user, code, purpose='phone_verify')
    if success:
        user.is_verified = True
        user.save(update_fields=['is_verified'])
    return success


# Password Reset 

def send_password_reset_otp(phone_number):
    """
    Look up the user by email or phone. Return an OTP if found, None otherwise.
    Deliberately does NOT reveal whether the user exists for security reasons.
    """
    user = None
    try:
        user = User.objects.get(phone_number=phone_number)
    except User.DoesNotExist:
        return  # silent, never reveald if account exists

    otp = create_otp(user, purpose='password_reset')
    # TODO: send via Arkesel — notifications app 
    logger.debug(f"[DEV] Password reset OTP for {phone_number}: {otp.code}") 
    return otp


@transaction.atomic
def reset_password(user: User, code: str, new_password: str) -> bool:
    """
    Verify the reset OTP then update the password.
    Returns True on success, False if OTP invalid.
    """
    if not verify_otp(user, code, purpose='password_reset'):
        return False
    user.set_password(new_password)
    user.save(update_fields=['password'])
    return True


def send_tenancy_confirmation_otp(user: User) -> OTP:
    """
    Create a tenancy-agreement-confirmation OTP and send it via SMS.
    Mirrors send_phone_verification_otp exactly — same create_otp()
    call, just a different purpose. Returns the OTP so the caller can
    trigger the SMS task.
    """
    otp = create_otp(user, purpose='tenancy_confirm')
    logger.debug(f"[DEV] Tenancy confirm OTP for {user.phone_number}: {otp.code}")
    return otp

