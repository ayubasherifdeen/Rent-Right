"""
accounts/views.py — thin views that delegate to services.py.

Every view does exactly one thing: validate input, call a service, 
redirect or render. No business logic lives here.
"""
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from httpcore import request
from .decorators import phone_verified_required, property_manager_required
from apps.accounts.models import ManagedProperty, User
from apps.listings.models import Property
from .forms import (
    LoginForm,
    OTPVerificationForm,
    PasswordResetConfirmForm,
    PasswordResetRequestForm,
    ProfileUpdateForm,
    RegistrationForm,
)
from .services import (
    confirm_phone_verification,
    landlords_managed_for,
    properties_managed_by,
    register_user,
    reset_password,
    invite_manager,
    accept_management_invite,
    revoke_management,
    send_password_reset_otp,
    send_phone_verification_otp,
)


# Registration 

@require_http_methods(['GET', 'POST'])
def register(request):
    if request.user.is_authenticated:
        return redirect('accounts:dashboard')

    form = RegistrationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        user = register_user(
            email=d['email'],
            password=d['password1'],
            first_name=d['first_name'],
            last_name=d['last_name'],
            phone_number=d['phone_number'],
            role=d['role'],
        )
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')

        # Trigger SMS OTP for phone verification
        otp = send_phone_verification_otp(user)
        # Store OTP id in session so verify view knows which OTP to check
        request.session['pending_otp_id'] = str(otp.id)

        # TODO: Call notifications.tasks.send_sms.delay(user.phone_number, otp.code)
        # (notifications app is built in Month 3 — slot is already designed)

        messages.success(request, f'Welcome, {user.first_name}! We sent a verification code to {user.phone_number}.')
        return redirect('accounts:verify_phone')

    return render(request, 'accounts/register.html', {'form': form})


#  Login / Logout

@require_http_methods(['GET', 'POST'])
def user_login(request):
    if request.user.is_authenticated:
        return redirect('accounts:dashboard')

    form = LoginForm(request, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.get_user()
        login(request, user)
        next_url = request.GET.get('next', 'accounts:dashboard')
        return redirect(next_url)

    return render(request, 'accounts/login.html', {'form': form})


@require_POST
@login_required
def user_logout(request):
    logout(request)
    messages.info(request, 'You have been logged out.')
    return redirect('accounts:login')


# Phone Verification 

@login_required
@require_http_methods(['GET', 'POST'])
def verify_phone(request):
    if request.user.is_verified:
        return redirect('accounts:dashboard')

    form = OTPVerificationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        success = confirm_phone_verification(request.user, form.cleaned_data['code'])
        if success:
            messages.success(request, 'Phone number verified successfully.')
            return redirect('accounts:dashboard')
        else:
            form.add_error('code', 'Invalid or expired code. Please try again.')

    return render(request, 'accounts/verify_phone.html', {'form': form})


@require_POST
@login_required
def resend_verification_otp(request):
    otp = send_phone_verification_otp(request.user)
    # TODO: Call notifications.tasks.send_sms.delay(...)
    messages.info(request, f'A new code has been sent to {request.user.phone_number}.')
    return redirect('accounts:verify_phone')


@login_required
def invite_manager_view(request, property_pk):
    """POST from edit_property.html or a. Only
    the property's own landlord may invite for it — enforced inside
    invite_manager() too, but checked here first for a clean 404
    instead of leaking property existence to non-owners."""
    property = get_object_or_404(Property, pk=property_pk, landlord=request.user)
    if request.method != "POST":
        raise PermissionDenied
    manager_email = request.POST.get("manager_email")
    manager = get_object_or_404(
        User, email=manager_email, userprofile__role="property_manager",
    )
    if manager.email == request.user.email:
        messages.error(request, "You can't invite yourself as a manager.")
        return redirect("listings:edit_property", pk=property.pk)
    try:
        invite_manager(property=property, landlord=request.user, manager=manager)
        messages.success(request, f"Invited {manager.email} to manage this property.")
    except ValidationError as e:
        messages.error(request, str(e))
    return redirect("listings:edit_property", pk=property.pk)
 
 
@property_manager_required
def manager_invites_view(request):
    """Manager's list of PENDING links awaiting their response."""
    invites = ManagedProperty.objects.filter(
        manager=request.user, status=ManagedProperty.Status.PENDING,
    ).select_related("property", "landlord")
    return render(request, "accounts/manager_invites.html", {"invites": invites})
 
 
@property_manager_required
def accept_management_invite_view(request, link_pk):
    link = get_object_or_404(ManagedProperty, pk=link_pk)
    if request.method != "POST":
        raise PermissionDenied
    accept_management_invite(link, request.user)
    return redirect("accounts:managed_properties")
 
 
@login_required
def revoke_management_view(request, link_pk):
    """Either the landlord or the manager on the link may revoke."""
    link = get_object_or_404(ManagedProperty, pk=link_pk)
    if request.method != "POST":
        raise PermissionDenied
    revoke_management(link, request.user)
    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER", "/")
    return redirect(next_url)
 
 
@property_manager_required
def managed_properties_view(request):
    """Return the list of properties managed by the current user."""
    landlord_id = request.GET.get("landlord")
    landlord_obj = get_object_or_404(User, pk=landlord_id) if landlord_id else None
    properties = properties_managed_by(request.user, landlord=landlord_obj)
    return render(request, "accounts/managed_properties.html", {
        "properties": properties,
        "landlords": landlords_managed_for(request.user),
        "selected_landlord": landlord_obj,
    })
 

# Dashboard

@login_required
def dashboard(request):
    """
    Role-based dashboard redirect. Each role gets their own dashboard view.
    This central dispatcher keeps URLs clean.
    """
    role = request.user.role
    if role == 'landlord':
        return redirect('accounts:landlord_dashboard')
    elif role == 'tenant':
        return redirect('accounts:tenant_dashboard')
    elif role == 'property_manager':
        return redirect('accounts:manager_dashboard')
    elif role == 'admin':
        return redirect('accounts:admin_dashboard')
    return render(request, 'accounts/dashboard.html')


@login_required
def landlord_dashboard(request):
    return render(request, 'accounts/dashboards/landlord.html', {
        'user': request.user,
    })


@login_required
def tenant_dashboard(request):
    return render(request, 'accounts/dashboards/tenant.html', {
        'user': request.user,
    })


@login_required
def manager_dashboard(request):
    managed_qs = properties_managed_by(request.user)
    pending_invites_count = ManagedProperty.objects.filter(
        manager=request.user, status=ManagedProperty.Status.PENDING,
    ).count()
    return render(request, 'accounts/dashboards/manager.html', {
        'user': request.user,
        'managed_count': managed_qs.count(),
        'recent_managed_properties': managed_qs.select_related('landlord')[:5],
        'pending_invites_count': pending_invites_count,
        'landlord_count': landlords_managed_for(request.user).count(),
    })


@login_required
def admin_dashboard(request):
    return render(request, 'accounts/dashboards/admin.html', {
        'user': request.user,
    })


# ─── Profile ──────────────────────────────────────────────────────────────────

@login_required
@require_http_methods(['GET', 'POST'])
def profile(request):
    form = ProfileUpdateForm(
        request.POST or None,
        request.FILES or None,
        instance=request.user.userprofile,
        user=request.user,
    )
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Profile updated successfully.')
        return redirect('accounts:profile')

    return render(request, 'accounts/profile.html', {'form': form})


#  Password Reset

@require_http_methods(['GET', 'POST'])
def password_reset_request(request):
    form = PasswordResetRequestForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        otp = send_password_reset_otp(form.cleaned_data['phone_number'])
        if otp:
            request.session['reset_user_id'] = str(otp.user.id)
            # TODO: Call notifications.tasks.send_sms.delay(...)
        # Always show success — never reveal whether the user exists
        messages.info(request, 'If an account was found, a reset code has been sent via SMS.')
        return redirect('accounts:password_reset_confirm')

    return render(request, 'accounts/password_reset_request.html', {'form': form})


@require_http_methods(['GET', 'POST'])
def password_reset_confirm(request):
    user_id = request.session.get('reset_user_id')
    if not user_id:
        return redirect('accounts:password_reset_request')

    from .models import User
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return redirect('accounts:password_reset_request')

    form = PasswordResetConfirmForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        success = reset_password(user, d['code'], d['new_password'])
        if success:
            del request.session['reset_user_id']
            messages.success(request, 'Password reset successfully. Please log in.')
            return redirect('accounts:login')
        else:
            form.add_error('code', 'Invalid or expired reset code.')

    return render(request, 'accounts/password_reset_confirm.html', {'form': form})

