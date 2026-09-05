"""
apps/analytics/services.py

Read-only cross-app aggregation, one function per role. No writes, no
side effects — safe to call from a view, a shell, or a test.

Scope rules (confirmed in session, not guessed):
  - Landlord dashboard = Property.landlord=user. Includes properties
    delegated to a manager, since ownership (not day-to-day management)
    defines "landlord" here. A landlord never manages someone else's
    property in this system.
  - Manager dashboard = ManagedProperty.manager=user,
    status=ManagedProperty.Status.ACTIVE. Managers don't own anything
    here — delegated properties only.
  - Tenant dashboard = Tenancy.tenant=user. Shaped differently from the
    other two: a tenant cares about their own status, not aggregate
    counts across many properties.

Reuses existing service functions rather than re-deriving their logic:
  - payments.services.get_instalment_schedule_with_status(tenancy)
  - negotiations.services.get_current_proposal(tenancy)
  - negotiations.services.MAX_NEGOTIATION_ROUNDS

Known unwritten field, do not use: Proposal.proposal_count. The model
column exists but nothing in negotiations/services.py ever sets it —
round counting there is done via tenancy.proposals.count() instead.
Flagged for separate cleanup; not analytics' problem to fix.
"""
from datetime import timedelta

from django.db.models import Avg, F, Sum
from django.utils import timezone

from apps.listings.models import Property
from apps.tenancies.models import Tenancy, TenancyStatus
from apps.maintenance.models import MaintenanceRequest, MaintenanceStatus
from apps.payments.models import Payment, PaymentStatus
from apps.payments.services import get_instalment_schedule_with_status
from apps.negotiations.models import ProposalStatus
from apps.negotiations.services import get_current_proposal, MAX_NEGOTIATION_ROUNDS

# ASSUMPTION — verify: ManagedProperty lives in apps.accounts per v15 §3.
# Field names (manager, property, is_active) were confirmed against real
# code earlier in this session, but the import path itself was not
# re-checked against this exact module.
from apps.accounts.models import ManagedProperty

MAINTENANCE_STALE_DAYS = 3
STUCK_ROUND_THRESHOLD = MAX_NEGOTIATION_ROUNDS - 1



def _property_scope_summary(properties, tenancies, active_tenancies):
    stale_cutoff = timezone.now() - timedelta(days=MAINTENANCE_STALE_DAYS)

    overdue_payments = sum(
        1
        for t in active_tenancies
        for entry in get_instalment_schedule_with_status(t)
        if entry["status"] == "overdue"
    )

    stuck_negotiations = 0
    for t in active_tenancies:
        current = get_current_proposal(t)
        if (
            current is not None
            and current.status == ProposalStatus.PENDING
            and t.proposals.count() >= STUCK_ROUND_THRESHOLD
        ):
            stuck_negotiations += 1

    action_items = {
        "overdue_payments": overdue_payments,
        "unacknowledged_maintenance": MaintenanceRequest.objects.filter(
            tenancy__in=tenancies,
            status=MaintenanceStatus.SUBMITTED,
            created_at__lt=stale_cutoff,
        ).count(),
        "stuck_negotiations": stuck_negotiations,
        "pending_otp_confirmations": tenancies.filter(
            status=TenancyStatus.PENDING_AGREEMENT,
        ).count(),
    }

    trends = {
        "total_properties": properties.count(),
        "active_tenancies_count": active_tenancies.count(),

        "monthly_income": Payment.objects.filter(
            tenancy__in=tenancies,
            status=PaymentStatus.SUCCESS,
            paid_at__month=timezone.now().month,
            paid_at__year=timezone.now().year,
        ).aggregate(total=Sum("amount"))["total"] or 0,

        "occupancy_rate": _occupancy_rate(properties, active_tenancies),

        "avg_maintenance_resolution_days": MaintenanceRequest.objects.filter(
            tenancy__in=tenancies,
            status=MaintenanceStatus.RESOLVED,
            resolved_at__isnull=False,
        ).annotate(
            resolution_time=F("resolved_at") - F("created_at")
        ).aggregate(avg=Avg("resolution_time"))["avg"],
    }

    return {"action_items": action_items, "trends": trends}


def _occupancy_rate(properties, active_tenancies):
    total = properties.count()
    if total == 0:
        return None
    occupied = active_tenancies.values("rental_property").distinct().count()
    return round(occupied / total * 100, 1)


def landlord_dashboard_data(user):
    """
    Everything landlord owns, including properties delegated to a manager — ownership,
    not day-to-day management, defines this scope.
    """
    properties = Property.objects.filter(landlord=user)
    tenancies = Tenancy.objects.filter(rental_property__in=properties)
    active_tenancies = tenancies.filter(status=TenancyStatus.ACTIVE)
    return _property_scope_summary(properties, tenancies, active_tenancies)


def manager_dashboard_data(user):
    """
    Everything `user` manages on someone else's behalf
    (ManagedProperty.manager=user, status=ACTIVE). Managers don't own
    anything in this system — this is a strict subset of some
    landlord's properties, never the manager's own dashboard data
    merged with a landlord view.
    """
    managed_property_ids = ManagedProperty.objects.filter(
        manager=user, status=ManagedProperty.Status.ACTIVE
    ).values_list("property_id", flat=True)

    properties = Property.objects.filter(id__in=managed_property_ids)
    tenancies = Tenancy.objects.filter(rental_property__in=properties)
    active_tenancies = tenancies.filter(status=TenancyStatus.ACTIVE)

    summary = _property_scope_summary(properties, tenancies, active_tenancies)
    summary["trends"]["landlord_count"] = (
        properties.values_list("landlord", flat=True).distinct().count()
    )
    return summary


def tenant_dashboard_data(user):
    """

    Everything tenant is involved in (Tenancy.tenant=user). Shaped differently
    """
    tenancies = Tenancy.objects.filter(tenant=user)
    active_tenancy = tenancies.filter(status=TenancyStatus.ACTIVE).first()

    stale_cutoff = timezone.now() - timedelta(days=MAINTENANCE_STALE_DAYS)

    own_overdue = []
    if active_tenancy is not None:
        own_overdue = [
            entry
            for entry in get_instalment_schedule_with_status(active_tenancy)
            if entry["status"] == "overdue"
        ]

    pending_agreement_tenancy = tenancies.filter(
        status=TenancyStatus.PENDING_AGREEMENT,
    ).first()

    action_items = {
        "overdue_payment_count": len(own_overdue),
        "next_due_entry": next(
            (
                entry
                for entry in (
                    get_instalment_schedule_with_status(active_tenancy)
                    if active_tenancy else []
                )
                if entry["status"] == "due"
            ),
            None,
        ),
        "own_open_maintenance": MaintenanceRequest.objects.filter(
            tenancy__in=tenancies,
            status__in=[MaintenanceStatus.SUBMITTED, MaintenanceStatus.ACKNOWLEDGED],
        ).count(),
        "own_stale_maintenance": MaintenanceRequest.objects.filter(
            tenancy__in=tenancies,
            status=MaintenanceStatus.SUBMITTED,
            created_at__lt=stale_cutoff,
        ).count(),
        "pending_agreement_step": pending_agreement_tenancy is not None,
        "pending_agreement_tenancy": pending_agreement_tenancy,
    }

    trends = {
        "payment_history": Payment.objects.filter(
            tenancy__in=tenancies,
            paid_by=user,
        ).order_by("-created_at")[:12],  # last 12 attempts, for a simple list/table
        "total_paid": Payment.objects.filter(
            tenancy__in=tenancies,
            status=PaymentStatus.SUCCESS,
        ).aggregate(total=Sum("amount"))["total"] or 0,
    }

    return {"action_items": action_items, "trends": trends}