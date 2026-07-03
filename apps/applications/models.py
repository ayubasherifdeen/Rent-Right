import uuid
from django.db import models
from django.conf import settings
from apps.listings.models import Property


class ApplicationStatus(models.TextChoices):
    PENDING   = 'pending',   'Pending'
    APPROVED  = 'approved',  'Approved'
    DECLINED  = 'declined',  'Declined'
    WITHDRAWN = 'withdrawn', 'Withdrawn'


class Application(models.Model):
    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rental_property     = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='applications')
    tenant       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='applications')
    status       = models.CharField(max_length=20, choices=ApplicationStatus.choices, default=ApplicationStatus.PENDING)
    move_in_date = models.DateField()
    message      = models.TextField(blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        # One live application per tenant per property.
        # "Live" means pending or approved — not withdrawn or declined.
        # This lets a tenant reapply after being declined or after withdrawing
        # without permanently locking them out. unique_together would do that
        # and it's the wrong rule.
        constraints = [
            models.UniqueConstraint(
                fields=['rental_property', 'tenant'],
                condition=models.Q(status__in=['pending', 'approved']),
                name='unique_active_application_per_tenant_per_property',
            )
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.tenant.get_full_name()} → {self.rental_property.title} ({self.status})"

    # ── Convenience predicates used in templates and services ─────────────────

    @property
    def is_pending(self):
        return self.status == ApplicationStatus.PENDING

    @property
    def is_approved(self):
        return self.status == ApplicationStatus.APPROVED

    @property
    def is_declined(self):
        return self.status == ApplicationStatus.DECLINED

    @property
    def is_withdrawn(self):
        return self.status == ApplicationStatus.WITHDRAWN

    @property
    def status_display(self):
        """Human-readable status for templates."""
        return self.get_status_display()
