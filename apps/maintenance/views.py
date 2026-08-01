"""
apps/maintenance/views.py

Access control follows handoff v15 §4's rule: 404, not 403, for "not your
object" — never reveal an object exists to someone who shouldn't see it.
`is_staff` is always an escape hatch, same as everywhere else.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404, request
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.models import ManagedProperty
from apps.accounts.services import can_act_on_property

from apps.tenancies.models import Tenancy, TenancyStatus

from . import services
from .forms import MaintenanceRequestForm, MaintenanceResolutionForm
from .models import MaintenanceRequest, MaintenanceStatus


def _tenancy_for_tenant_or_404(tenancy_pk, user):
    tenancy = get_object_or_404(Tenancy, pk=tenancy_pk)
    if tenancy.tenant_id != user.id:
        raise Http404
    return tenancy


def _request_for_user_or_404(pk, user):
    """
    A maintenance request is visible to the tenant who filed it, or to
    anyone who can act on the underlying property (landlord or delegated
    manager). Staff always pass.
    """
    maintenance_request = get_object_or_404(
        MaintenanceRequest.objects.select_related(
            "tenancy", "tenancy__rental_property", "reported_by"
        ),
        pk=pk,
    )
    tenancy = maintenance_request.tenancy
    is_reporter = maintenance_request.reported_by_id == user.id
    is_property_party = can_act_on_property(user, tenancy.rental_property)
    if not (is_reporter or is_property_party or user.is_staff):
        raise Http404
    return maintenance_request


@login_required
def report_maintenance(request, tenancy_pk):
    tenancy = _tenancy_for_tenant_or_404(tenancy_pk, request.user)

    if request.method == "POST":
        form = MaintenanceRequestForm(request.POST)
        if form.is_valid():
            try:
                maintenance_request = services.create_maintenance_request(
                    tenancy=tenancy,
                    reported_by=request.user,
                    category=form.cleaned_data["category"],
                    title=form.cleaned_data["title"],
                    description=form.cleaned_data["description"],
                    media=request.FILES.getlist("media"),
                )
            except ValueError as e:
                messages.error(request, str(e))
            else:
                messages.success(request, "Maintenance report submitted.")
                return redirect("maintenance:detail", pk=maintenance_request.pk)
    else:
        form = MaintenanceRequestForm()

    return render(
        request,
        "maintenance/report_form.html",
        {"form": form, "tenancy": tenancy},
    )


@login_required
def tenant_maintenance_list(request):
    maintenance_requests = (
        MaintenanceRequest.objects.filter(reported_by=request.user)
        .select_related("tenancy", "tenancy__rental_property")
    )
    active_tenancies = Tenancy.objects.filter(
        tenant=request.user, status=TenancyStatus.ACTIVE
    ).select_related("rental_property")
    return render(
        request,
        "maintenance/tenant_list.html",
        {
            "maintenance_requests": maintenance_requests,
            "active_tenancies": active_tenancies,
        },
    )


@login_required
def landlord_maintenance_list(request):
    from apps.accounts.models import ManagedProperty

    managed_property_ids = ManagedProperty.objects.filter(
        manager=request.user, status="active"
    ).values_list("property_id", flat=True)

    maintenance_requests = (
        MaintenanceRequest.objects.filter(
            Q(tenancy__landlord=request.user)
            | Q(tenancy__rental_property_id__in=managed_property_ids)
        )
        .select_related("tenancy", "tenancy__rental_property", "reported_by")
        .distinct()
    )
    #filter by tenancy or property if query params are present
    filtered_tenancy = None
    tenancy_id = request.GET.get("tenancy")
    property_id = request.GET.get("property")
    if tenancy_id:
        maintenance_requests = maintenance_requests.filter(tenancy_id=tenancy_id)
        filtered_tenancy = maintenance_requests.first() and maintenance_requests.first().tenancy
    elif property_id:
        maintenance_requests = maintenance_requests.filter(
            tenancy__rental_property_id=property_id
        )

    status_filter = request.GET.get("status")
    if status_filter in MaintenanceStatus.values:
        maintenance_requests = maintenance_requests.filter(status=status_filter)

    counts = {
        "total": maintenance_requests.count(),
        "submitted": maintenance_requests.filter(status=MaintenanceStatus.SUBMITTED).count(),
        "acknowledged": maintenance_requests.filter(status=MaintenanceStatus.ACKNOWLEDGED).count(),
        "resolved": maintenance_requests.filter(status=MaintenanceStatus.RESOLVED).count(),
    }
    return render(
        request,
        "maintenance/landlord_list.html",
        {
            "maintenance_requests": maintenance_requests,
            "counts": counts,
            "filtered_tenancy": filtered_tenancy,
            "status_filter": status_filter,
        }
         
    )


@login_required
def maintenance_detail(request, pk):
    maintenance_request = _request_for_user_or_404(pk, request.user)
    is_reporter = maintenance_request.reported_by_id == request.user.id
    can_manage = can_act_on_property(
        request.user, maintenance_request.tenancy.rental_property
    )
    return render(
        request,
        "maintenance/detail.html",
        {
            "maintenance_request": maintenance_request,
            "updates": maintenance_request.updates.select_related("actor"),
            "media": maintenance_request.media.select_related("uploaded_by"),
            "is_reporter": is_reporter,
            "can_manage": can_manage,
            "resolution_form": MaintenanceResolutionForm(),
        },
    )


@login_required
def acknowledge_maintenance(request, pk):
    if request.method != "POST":
        raise Http404
    maintenance_request = _request_for_user_or_404(pk, request.user)
    if not can_act_on_property(request.user, maintenance_request.tenancy.rental_property):
        raise Http404
    try:
        services.acknowledge_request(maintenance_request, actor=request.user)
    except ValueError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, "Marked as acknowledged.")
    return redirect("maintenance:detail", pk=pk)


@login_required
def resolve_maintenance(request, pk):
    maintenance_request = _request_for_user_or_404(pk, request.user)
    if not can_act_on_property(request.user, maintenance_request.tenancy.rental_property):
        raise Http404

    if request.method == "POST":
        form = MaintenanceResolutionForm(request.POST)
        if form.is_valid():
            try:
                services.resolve_request(
                    maintenance_request,
                    actor=request.user,
                    note=form.cleaned_data["note"],
                    media=request.FILES.getlist("media"),
                )
            except ValueError as e:
                messages.error(request, str(e))
            else:
                messages.success(request, "Marked as resolved.")
                return redirect("maintenance:detail", pk=pk)

    return redirect("maintenance:detail", pk=pk)


@login_required
def cancel_maintenance(request, pk):
    if request.method != "POST":
        raise Http404
    maintenance_request = _request_for_user_or_404(pk, request.user)
    if maintenance_request.reported_by_id != request.user.id:
        raise Http404
    try:
        services.cancel_request(maintenance_request, actor=request.user)
    except ValueError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, "Request cancelled.")
    return redirect("maintenance:tenant_list")
