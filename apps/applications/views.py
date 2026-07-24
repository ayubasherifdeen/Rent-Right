"""
applications/views.py

Thin views. The pattern for every mutating view:
  1. Validate the request (auth decorator, method check)
  2. Fetch the object (get_object_or_404 — never .get())
  3. Call the service
  4. Catch ValueError → meaningful HTTP response
  5. Redirect on success

Views never contain business logic. If you find yourself writing an if-statement
about application status inside a view, that logic belongs in services.py.
"""

from multiprocessing import context

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.http import HttpResponseForbidden

from apps.accounts import models
from apps.accounts.decorators import (
    tenant_required,
    landlord_or_manager_required,
    phone_verified_required,
)
from apps.listings.models import Property
from .models import Application, ApplicationStatus
from .forms import ApplicationForm
from . import services


# Tenant views

@login_required
@phone_verified_required
@tenant_required
def apply(request, pk):
    """
    GET  — render the application form (shown inside or alongside the listing detail).
    POST — submit the application via the service layer.

    apply for tenancy. Only tenants can apply
    """
    property_obj = get_object_or_404(Property, pk=pk)

    # A landlord cannot apply to their own property. Service catches role,
    if property_obj.status != 'active':
        messages.error(request, "This property is not currently accepting applications.")
        return redirect('listings:property_detail', pk=pk)

    if request.method == 'POST':
        form = ApplicationForm(request.POST)
        if form.is_valid():
            try:
                services.submit_application(
                    tenant=request.user,
                    property_obj=property_obj,
                    move_in_date=form.cleaned_data['move_in_date'],
                    message=form.cleaned_data.get('message', ''),
                )
                messages.success(
                    request,
                    f"Application submitted for {property_obj.title}. "
                    f"The landlord will be in touch."
                )
                return redirect('applications:my_applications')
            except ValueError as e:
                # Service rejected the application — show the reason to the tenant.
                messages.error(request, str(e))
                return render(request, 'applications/apply.html', {
                    'form': form,
                    'property': property_obj,
                }, status=400)
    else:
        form = ApplicationForm()

    return render(request, 'applications/apply.html', {
        'form': form,
        'property': property_obj,
    })


@login_required
@tenant_required
def my_applications(request):
    """
    Tenant's dashboard: all their applications, newest first.
    Filtered to the logged-in user only — a tenant can never see another tenant's applications.
    """
    applications = (
        Application.objects
        .filter(tenant=request.user)
        .select_related('rental_property', 'rental_property__landlord')
        .order_by('-created_at')
    )
    return render(request, 'applications/my_applications.html', {
        'applications': applications,
    })


# Landlord views

@login_required
@landlord_or_manager_required
def received_applications(request):
    """
    Landlord's dashboard: all applications for their properties.
    Filtered to only show applications for properties this landlord owns.
    A manager sees applications for all properties they manage.
    """
    from apps.accounts.services import properties_managed_by, landlords_managed_for

    is_manager = request.user.is_property_manager()
    base_qs = (
        Application.objects
        .select_related('rental_property', 'rental_property__landlord', 'tenant', 'tenant__userprofile')
    )

    available_landlords = None
    selected_landlord = None

    if is_manager:
        applications = base_qs.filter(rental_property__in=properties_managed_by(request.user))

        selected_landlord = request.GET.get('landlord') or None
        if selected_landlord:
            applications = applications.filter(rental_property__landlord_id=selected_landlord)

        available_landlords = landlords_managed_for(request.user)
    else:
        applications = base_qs.filter(rental_property__landlord=request.user)

    #status filter
    selected_status = request.GET.get('status') or None
    valid_statuses = {choice.value for choice in ApplicationStatus}
    if selected_status not in valid_statuses:
        selected_status = None
    if selected_status:
        applications = applications.filter(status=selected_status)

    applications = applications.order_by('-created_at')

    from apps.tenancies.models import Tenancy
    tenancy_app_pks = set(
        Tenancy.objects.filter(application__in=applications).values_list("application_id", flat=True)
    )

    context = {
        'applications': applications,
        'tenancy_app_pks': tenancy_app_pks,
        'is_manager': is_manager,
        'available_landlords': available_landlords,
        'selected_landlord': selected_landlord,
        'selected_status': selected_status,
        'status_choices': ApplicationStatus.choices,
    }
    
    return render(request, 'applications/received_applications.html', context)


@login_required
@landlord_or_manager_required
@require_POST
def approve_application(request, pk):
    """
    POST /applications/<uuid>/approve/
    Idempotency note: approving an already-approved application raises ValueError.
    The service error is surfaced as a flash message; landlord is redirected back.
    """
    application = get_object_or_404(Application, pk=pk)
    try:
        services.approve_application(application, landlord=request.user)
        messages.success(
            request,
            f"Application approved. {application.tenant.get_full_name()} has been notified."
        )
    except ValueError as e:
        messages.error(request, str(e))
    return redirect('applications:received_applications')


@login_required
@landlord_or_manager_required
@require_POST
def decline_application(request, pk):
    """
    POST /applications/<uuid>/decline/
    Accepts an optional 'reason' field from the POST body for future use.
    """
    application = get_object_or_404(Application, pk=pk)
    reason = request.POST.get('reason', '')
    try:
        services.decline_application(application, landlord=request.user, reason=reason)
        messages.success(
            request,
            f"Application declined. {application.tenant.get_full_name()} has been notified."
        )
    except ValueError as e:
        messages.error(request, str(e))
    return redirect('applications:received_applications')


@login_required
@require_POST
def withdraw_application(request, pk):
    """
    POST /applications/<uuid>/withdraw/
    No role decorator — both tenants and (potentially) admins could reach this.
    The service guards on application.tenant == request.user, which is the real check.
    """
    application = get_object_or_404(Application, pk=pk)
    try:
        services.withdraw_application(application, tenant=request.user)
        messages.success(request, "Application withdrawn.")
    except ValueError as e:
        messages.error(request, str(e))
    return redirect('applications:my_applications')
