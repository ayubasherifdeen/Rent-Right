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


def _get_accepted_proposal(tenancy):
    """
    Returns the ACCEPTED Proposal for this tenancy, or None.
    """
    from apps.negotiations.models import ProposalStatus

    return tenancy.proposals.filter(status=ProposalStatus.ACCEPTED).first()


def _financial_display_context(tenancy):
    """
    Computes the figures templates should actually render: negotiated
    (proposal.advance_months, and advance_amount recomputed from it)
    when an accepted Proposal exists, falling back to the tenancy's own
    frozen advance_months/advance_amount otherwise.
    """
    proposal = _get_accepted_proposal(tenancy)
    if proposal:
        display_advance_months = proposal.advance_months
        display_advance_amount = tenancy.monthly_rent * proposal.advance_months
    else:
        display_advance_months = tenancy.advance_months
        display_advance_amount = tenancy.advance_amount

    return {
        "proposal": proposal,
        "display_advance_months": display_advance_months,
        "display_advance_amount": display_advance_amount,
    }

def generate_rent_card(tenancy, generated_by=None):
    """
    Renders tenancies/rent_card_template.html (carried over unchanged
    from the tenancies app, handoff v8 §2.9) into a PDF and stores it as
    a Document generic-FK'd to the Tenancy.
    """
    context = {"tenancy": tenancy, **_financial_display_context(tenancy)}
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
    context = {"agreement": agreement, "tenancy": agreement.tenancy, **_financial_display_context(agreement.tenancy)}
    pdf_bytes = _render_pdf("documents/tenancy_agreement_template.html", context)

    document = Document.objects.create(
        document_type=DocumentType.TENANCY_AGREEMENT,
        content_type=ContentType.objects.get_for_model(agreement),
        object_id=agreement.pk,
        generated_by=generated_by,
    )
    document.file.save(f"tenancy_agreement_{agreement.pk}.pdf", ContentFile(pdf_bytes), save=True)
    return document


def generate_instalment_addendum(agreement, generated_by=None):
    """
    Generates the instalment addendum PDF


    Deliberately NOT called unconditionally for every Agreement — see
    the caller in tenancies._execute_agreement(), which only calls this
    when the accepted Proposal isn't the opening one (i.e. terms were
    actually negotiated away from the tenancy's original frozen values).
    If accept_proposal() ran with zero counters, the "negotiated" terms
    are identical to the tenancy's own terms and there's nothing for an
    addendum to add.
    """
    proposal = _get_accepted_proposal(agreement.tenancy)
    context = {"agreement": agreement, "tenancy": agreement.tenancy, "proposal": proposal, **_financial_display_context(agreement.tenancy)}
    pdf_bytes = _render_pdf("documents/instalment_addendum_template.html", context)

    document = Document.objects.create(
        document_type=DocumentType.INSTALMENT_ADDENDUM,
        content_type=ContentType.objects.get_for_model(agreement),
        object_id=agreement.pk,
        generated_by=generated_by,
    )
    document.file.save(
        f"instalment_addendum_{agreement.pk}.pdf", ContentFile(pdf_bytes), save=True
    )
    return document


def get_documents_for(obj):
    """Return all Documents generic-FK'd to a given object (Tenancy, Agreement, ...)."""
    ct = ContentType.objects.get_for_model(obj)
    return Document.objects.filter(content_type=ct, object_id=obj.pk)
