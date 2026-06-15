"""
Role-based access decorators. Use these on views instead of
manually checking request.user.role every time.

Usage:
    @login_required
    @landlord_required
    def my_listing_view(request): ...
"""
from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .models import Role


def role_required(*roles):
    """Generic decorator — pass one or more Role values."""
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapper(request, *args, **kwargs):
            if request.user.role not in roles:
                raise PermissionDenied
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def landlord_required(view_func):
    return role_required(Role.LANDLORD)(view_func)


def tenant_required(view_func):
    return role_required(Role.TENANT)(view_func)


def property_manager_required(view_func):
    return role_required(Role.PROPERTY_MANAGER)(view_func)


def landlord_or_manager_required(view_func):
    return role_required(Role.LANDLORD, Role.PROPERTY_MANAGER)(view_func)


def admin_required(view_func):
    return role_required(Role.ADMIN)(view_func)


def phone_verified_required(view_func):
    """
    Ensure the user has verified their phone number before accessing
    sensitive operations (payments, OTP confirmations, etc.)
    """
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_verified:
            from django.shortcuts import redirect
            from django.urls import reverse
            return redirect(reverse('accounts:verify_phone'))
        return view_func(request, *args, **kwargs)
    return wrapper

