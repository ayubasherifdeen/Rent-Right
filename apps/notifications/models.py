"""
apps/notifications/models.py

One model: an append-only log of every notification attempt. Not asked
for explicitly, but it's the same reasoning that produced MaintenanceUpdate
and the immutable Proposal chain (handoff v15 §4, maintenance §1) — cheap
to add now, and the only way to answer "was this person notified" later
without grepping dev logs. If `disputes` ever needs "was the tenant
notified of X", it reads this table, same as it'll read the maintenance
trail and negotiation chain.
"""

import uuid

from django.conf import settings
from django.db import models


class NotificationPurpose(models.TextChoices):
    OTP = "otp", "OTP / Verification"
    TENANCY = "tenancy", "Tenancy / Agreement"
    NEGOTIATION = "negotiation", "Negotiation"
    PAYMENT = "payment", "Payment"
    MAINTENANCE = "maintenance", "Maintenance"
    APPLICATION = "application", "Application"
    GENERAL = "general", "General"


class NotificationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"
    DRY_RUN = "dry_run", "Dry Run"


class Notification(models.Model):
    """
    One row per SMS attempt, success or failure. Never updated after the
    fact except to record the outcome of the attempt itself — this is a
    log, not a queue; nothing re-reads or re-processes these rows.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    purpose = models.CharField(
        max_length=20,
        choices=NotificationPurpose.choices,
        default=NotificationPurpose.GENERAL,
    )
    message = models.TextField()
    status = models.CharField(
        max_length=10,
        choices=NotificationStatus.choices,
        default=NotificationStatus.PENDING,
    )
    provider_message_id = models.CharField(max_length=100, blank=True)
    error = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.get_status_display()}] {self.get_purpose_display()} → {self.user}"
