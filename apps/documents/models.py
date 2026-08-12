import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class DocumentType(models.TextChoices):
    RENT_CARD = "rent_card", "Rent Card"
    TENANCY_AGREEMENT = "tenancy_agreement", "Tenancy Agreement"
    INSTALMENT_ADDENDUM = "instalment_addendum", "Instalment Addendum"
    PAYMENT_RECEIPT     = "payment_receipt",      "Payment Receipt"
    DISPUTE_PACKET = "dispute_packet", "Dispute Packet"
    
class Document(models.Model):
    """
    Generic PDF vault. Generic-FK'd to whatever generated it (Tenancy,
    Agreement, and future source types)
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    document_type = models.CharField(max_length=32, choices=DocumentType.choices)

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.UUIDField()
    content_object = GenericForeignKey("content_type", "object_id")

    file = models.FileField(upload_to="documents/%Y/%m/")

    generated_at = models.DateTimeField(auto_now_add=True)
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generated_documents",
    )

    class Meta:
        ordering = ["-generated_at"]
        indexes = [
            models.Index(fields=["content_type", "object_id"]),
        ]

    def __str__(self):
        return f"{self.get_document_type_display()} ({self.content_type.model} #{self.object_id})"
