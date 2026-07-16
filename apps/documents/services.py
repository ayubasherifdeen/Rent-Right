"""
PDF generation services. 
Uses WeasyPrint (HTML/CSS -> PDF) 
"""

from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.template.loader import render_to_string

from weasyprint import HTML

from .models import Document, DocumentType


def _render_pdf(template_name, context):
    html_string = render_to_string(template_name, context)
    return HTML(string=html_string).write_pdf()


def generate_rent_card(tenancy, generated_by=None):
    """
    Renders tenancies/rent_card_template.html (carried over unchanged
    from the tenancies app, handoff v8 §2.9) into a PDF and stores it as
    a Document generic-FK'd to the Tenancy.

    NOTE: field names below (rental_property, landlord, tenant,
    monthly_rent, advance_months, start_date, end_date) are now
    confirmed against the real create_tenancy() in
    apps/tenancies/services.py — no longer a guess. Still unconfirmed:
    the actual variable names rent_card_template.html expects — I have
    the real services.py but not the real template contents. If the
    template was written before this vault existed it may use different
    variable names than the ones below; adjust the context dict to match
    if generation renders blank/wrong fields.
    """
    context = {"tenancy": tenancy}
    pdf_bytes = _render_pdf("tenancies/rent_card_template.html", context)

    document = Document.objects.create(
        document_type=DocumentType.RENT_CARD,
        content_type=ContentType.objects.get_for_model(tenancy),
        object_id=tenancy.pk,
        generated_by=generated_by,
    )
    document.file.save(f"rent_card_{tenancy.pk}.pdf", ContentFile(pdf_bytes), save=True)
    return document


def generate_tenancy_agreement(agreement, generated_by=None):
    """
    agreement fields (.tenancy, .special_conditions,
    .landlord_confirmed_at, .tenant_confirmed_at, .fully_executed_at)
    confirmed per handoff v8 §2.2. Tenancy fields (.rental_property,
    .landlord, .tenant, .monthly_rent, .advance_months, .start_date,
    .end_date) now confirmed against the real create_tenancy() in
    apps/tenancies/services.py.
    """
    context = {"agreement": agreement, "tenancy": agreement.tenancy}
    pdf_bytes = _render_pdf("documents/tenancy_agreement_template.html", context)

    document = Document.objects.create(
        document_type=DocumentType.TENANCY_AGREEMENT,
        content_type=ContentType.objects.get_for_model(agreement),
        object_id=agreement.pk,
        generated_by=generated_by,
    )
    document.file.save(f"tenancy_agreement_{agreement.pk}.pdf", ContentFile(pdf_bytes), save=True)
    return document


def get_documents_for(obj):
    """Return all Documents generic-FK'd to a given object (Tenancy, Agreement, ...)."""
    ct = ContentType.objects.get_for_model(obj)
    return Document.objects.filter(content_type=ct, object_id=obj.pk)
