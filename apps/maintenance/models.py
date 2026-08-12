"""
apps/maintenance/models.py

Scope, deliberately: a tenant reports something that needs attention, with
optional photo/video evidence. The landlord/manager acknowledges it and, once
dealt with (outside the app), marks it resolved with optional evidence of their own. Every
step is logged to an append-only trail.

a future`disputes` app should be able to read history straight off this model
without reconstructing it from mutated fields.
"""
import uuid
from django.conf import settings
from django.db import models

from apps.tenancies.models import Tenancy

from cloudinary.models import CloudinaryField


class MaintenanceCategory(models.TextChoices):
    PLUMBING = "plumbing", "Plumbing"
    ELECTRICAL = "electrical", "Electrical"
    STRUCTURAL = "structural", "Structural"
    APPLIANCE = "appliance", "Appliance"
    PEST = "pest", "Pest Control"
    SECURITY = "security", "Security"
    OTHER = "other", "Other"


class MaintenanceStatus(models.TextChoices):
    SUBMITTED = "submitted", "Submitted"
    ACKNOWLEDGED = "acknowledged", "Acknowledged"
    RESOLVED = "resolved", "Resolved"
    CANCELLED = "cancelled", "Cancelled"


class MediaStage(models.TextChoices):
    REPORTED = "reported", "Reported"
    RESOLUTION = "resolution", "Resolution"


class MediaType(models.TextChoices):
    IMAGE = "image", "Image"
    VIDEO = "video", "Video"


class MaintenanceRequest(models.Model):
    """
    One issue, reported once, tracked to resolution. Tied to a Tenancy
    (not directly to a Property) 
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenancy = models.ForeignKey(
        Tenancy, on_delete=models.PROTECT, related_name="maintenance_requests"
    )
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="maintenance_requests_filed",
    )
    category = models.CharField(max_length=20, choices=MaintenanceCategory.choices)
    title = models.CharField(max_length=150)
    description = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=MaintenanceStatus.choices,
        default=MaintenanceStatus.SUBMITTED,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.get_status_display()}] {self.title} (tenancy #{self.tenancy_id})"


class MaintenanceUpdate(models.Model):
    """
    This is the entire audit trail a future disputes app would need; don't add a
    "latest note" field to MaintenanceRequest itself as a shortcut, since
    that would let history quietly get overwritten.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.ForeignKey(
        MaintenanceRequest, on_delete=models.CASCADE, related_name="updates"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="maintenance_updates_made",
    )
    old_status = models.CharField(max_length=20, choices=MaintenanceStatus.choices)
    new_status = models.CharField(max_length=20, choices=MaintenanceStatus.choices)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Request #{self.request_id}: {self.old_status} -> {self.new_status}"


class MaintenanceRequestMedia(models.Model):
    """
    Evidence, tagged by which end of the process it was taken at. The
    `stage` field is the one addition beyond a plain photo gallery — without
    it, a resolved request's photos can't distinguish "here's the problem"
    from "here's it fixed," which is exactly the distinction that matters
    if this ever gets pulled into a dispute.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.ForeignKey(
        MaintenanceRequest, on_delete=models.CASCADE, related_name="media"
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="maintenance_media_uploaded",
    )
    file = CloudinaryField("file", resource_type="auto")
    media_type = models.CharField(max_length=10, choices=MediaType.choices)
    stage = models.CharField(
        max_length=20, choices=MediaStage.choices, default=MediaStage.REPORTED
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.get_media_type_display()} ({self.get_stage_display()}) on request #{self.request_id}"
