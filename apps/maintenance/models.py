"""
apps/maintenance/models.py

Scope, deliberately: a tenant reports something that needs attention, with
optional photo evidence. The landlord/manager acknowledges it and, once
dealt with (outside the app — a plumber getting called is not this app's
business), marks it resolved with optional evidence of their own. Every
step is logged to an append-only trail.

Design choices carried over from the rest of the codebase (handoff v15 §4):
  - Financial/legal apps use `ValueError`-raising services + 404-not-403
    access control. This app follows the same shape in services.py/views.py.
  - The `MaintenanceUpdate` trail is append-only, mirroring the immutable
    `Proposal` chain in `negotiations` — for the same reason: a future
    `disputes` app should be able to read history straight off this model
    without reconstructing it from mutated fields.
"""
import uuid
from django.conf import settings
from django.db import models

# ASSUMPTION — verify against the real project:
# `Tenancy` lives in apps.tenancies.models per handoff v15 §1/§6.8. Field
# names used below (`tenancy.landlord`, `tenancy.rental_property`,
# `tenancy.tenant`, `TenancyStatus.ACTIVE`) are taken directly from code
# snippets quoted in the handoff (§6.8's `landlord_tenancies` view), not
# guessed — but double check `TenancyStatus.ACTIVE` is the exact member
# name before running migrations.
from apps.tenancies.models import Tenancy

# ASSUMPTION — the handoff (§2) lists Cloudinary as the media backend and
# says photos elsewhere (PropertyPhoto) already use it. `CloudinaryField`
# is the standard way to do that. If the real PropertyPhoto model uses a
# different field/import, mirror that instead for consistency.
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
    (not directly to a Property) so that:
      1. Access control is free — `tenancy.landlord` /
         `can_act_on_property(user, tenancy.rental_property)` already
         answers "can this user touch this" (handoff v15 §4).
      2. History survives the tenancy ending — `on_delete=PROTECT` means
         a tenancy can't be deleted out from under its maintenance record.
      3. It's unambiguous which tenant reported it, without a second join.
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
    Append-only trail. Never updated in place, never deleted — one row per
    status transition, always naming who did it and when. This is the
    entire audit trail a future disputes app would need; don't add a
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
    d = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.ForeignKey(
        MaintenanceRequest, on_delete=models.CASCADE, related_name="photos"
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
