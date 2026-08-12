"""
Services raise ValueError on business-rule violations, never Django HTTP
exceptions this keeps them callable from the shell,
tests, or a future management command without a request/response cycle.
"""

import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.tenancies.models import TenancyStatus

from .models import (
    MaintenanceRequest,
    MaintenanceRequestMedia,
    MaintenanceStatus,
    MaintenanceUpdate,
    MediaStage,
    MediaType,
)

from apps.notifications.services import notify_user
from apps.notifications.models import NotificationPurpose

logger = logging.getLogger(__name__)


def _media_type_for(uploaded_file):
    """
    Classify by the browser-supplied content type rather than asking the
    uploader to pick — one less form field, and it can't be gotten wrong.
    Falls back to image, since that's the safer Cloudinary default if a
    content type is ever missing.
    """
    content_type = getattr(uploaded_file, "content_type", "") or ""
    return MediaType.VIDEO if content_type.startswith("video/") else MediaType.IMAGE


def _notification_recipients(tenancy):
    """
    Landlord plus any currently-active delegated manager(s) for the
    property. A request should reach whoever actually checks in on the
    property day to day, not just the landlord on record — access already
    works this way via can_act_on_property() in views.py, notifications
    should match.

    ASSUMPTION — same as views.landlord_maintenance_list: ManagedProperty
    field names (`manager`, `property`, `status`) are a best guess.
    Confirm against the real accounts model.
    """
    from apps.accounts.models import ManagedProperty

    recipients = [tenancy.landlord]
    manager_ids = ManagedProperty.objects.filter(
        property=tenancy.rental_property, status='active'
    ).values_list("manager_id", flat=True)
    if manager_ids:
        from django.contrib.auth import get_user_model

        recipients += list(get_user_model().objects.filter(id__in=manager_ids))
    return recipients


def create_maintenance_request(
    tenancy, reported_by, category, title, description, media=None
):
    """
    File a new report. Only allowed on an active tenancy — a request tied
    to a tenancy that never activated, or that already ended, has no
    landlord workflow to land in.
    """
    if tenancy.status != TenancyStatus.ACTIVE:
        raise ValueError("Maintenance requests can only be filed on an active tenancy.")

    with transaction.atomic():
        maintenance_request = MaintenanceRequest.objects.create(
            tenancy=tenancy,
            reported_by=reported_by,
            category=category,
            title=title,
            description=description,
        )
        MaintenanceUpdate.objects.create(
            request=maintenance_request,
            actor=reported_by,
            old_status=MaintenanceStatus.SUBMITTED,
            new_status=MaintenanceStatus.SUBMITTED,
            note="Request submitted.",
        )
        for uploaded_file in media or []:
            MaintenanceRequestMedia.objects.create(
                request=maintenance_request,
                uploaded_by=reported_by,
                file=uploaded_file,
                media_type=_media_type_for(uploaded_file),
                stage=MediaStage.REPORTED,
            )

    logger.debug(
        f"[MAINTENANCE] Request #{maintenance_request.pk} filed on tenancy #{tenancy.pk}"
    )

    for recipient in _notification_recipients(tenancy):
        notify_user(recipient, 
                    f"New maintenance report: {maintenance_request.get_category_display()} — {maintenance_request.title}",
                     purpose=NotificationPurpose.MAINTENANCE)

    return maintenance_request


def acknowledge_request(maintenance_request, actor):
    """Landlord/manager confirms they've seen it. One-way, one-time."""
    if maintenance_request.status != MaintenanceStatus.SUBMITTED:
        raise ValueError("Only a submitted request can be acknowledged.")

    with transaction.atomic():
        old_status = maintenance_request.status
        maintenance_request.status = MaintenanceStatus.ACKNOWLEDGED
        maintenance_request.save(update_fields=["status"])
        MaintenanceUpdate.objects.create(
            request=maintenance_request,
            actor=actor,
            old_status=old_status,
            new_status=maintenance_request.status,
            note="Acknowledged by landlord/manager.",
        )

    notify_user(
        maintenance_request.reported_by,
        "Your maintenance report has been acknowledged.",
        purpose=NotificationPurpose.MAINTENANCE)
    return maintenance_request


def resolve_request(maintenance_request, actor, note="", media=None):
    """
    Mark it done. Callable from either SUBMITTED or ACKNOWLEDGED — a
    landlord who fixes something the same day shouldn't be forced through
    an acknowledge step first just to satisfy the state machine.
    """
    if maintenance_request.status not in (
        MaintenanceStatus.SUBMITTED,
        MaintenanceStatus.ACKNOWLEDGED,
    ):
        raise ValueError("Only a submitted or acknowledged request can be resolved.")

    with transaction.atomic():
        old_status = maintenance_request.status
        maintenance_request.status = MaintenanceStatus.RESOLVED
        maintenance_request.resolved_at = timezone.now()
        maintenance_request.save(update_fields=["status", "resolved_at"])
        MaintenanceUpdate.objects.create(
            request=maintenance_request,
            actor=actor,
            old_status=old_status,
            new_status=maintenance_request.status,
            note=note,
        )
        for uploaded_file in media or []:
            MaintenanceRequestMedia.objects.create(
                request=maintenance_request,
                uploaded_by=actor,
                file=uploaded_file,
                media_type=_media_type_for(uploaded_file),
                stage=MediaStage.RESOLUTION,
            )

    notify_user(
        maintenance_request.reported_by,
        "Your maintenance report has been marked resolved.",
        purpose=NotificationPurpose.MAINTENANCE
    )
    return maintenance_request


def cancel_request(maintenance_request, actor, note=""):
    """Tenant withdraws a report (duplicate, resolved themselves, etc.)."""
    if maintenance_request.status in (
        MaintenanceStatus.RESOLVED,
        MaintenanceStatus.CANCELLED,
    ):
        raise ValueError("A resolved or already-cancelled request cannot be cancelled.")

    with transaction.atomic():
        old_status = maintenance_request.status
        maintenance_request.status = MaintenanceStatus.CANCELLED
        maintenance_request.save(update_fields=["status"])
        MaintenanceUpdate.objects.create(
            request=maintenance_request,
            actor=actor,
            old_status=old_status,
            new_status=maintenance_request.status,
            note=note,
        )
    for recipient in _notification_recipients(maintenance_request.tenancy):
        notify_user(
            recipient,
            f"Maintenance report cancelled: {maintenance_request.get_category_display()} — {maintenance_request.title}",
            purpose=NotificationPurpose.MAINTENANCE
        )   
    return maintenance_request
