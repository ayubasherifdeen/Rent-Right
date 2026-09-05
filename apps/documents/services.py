"""
PDF generation services. 
Uses WeasyPrint (HTML/CSS -> PDF) 
"""

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from django.core.files.base import ContentFile
from django.template.loader import render_to_string

from weasyprint import HTML

from .models import Document, DocumentType
from apps.tenancies.models import TenancyStatus


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
    from apps.payments.models import PaymentStatus
    payment_history = tenancy.payments.filter(status=PaymentStatus.SUCCESS).order_by("paid_at")
    context = {"tenancy": tenancy, "payment_history": payment_history, **_financial_display_context(tenancy)}
    pdf_bytes = _render_pdf("tenancies/rent_card_template.html", context)

    document = Document.objects.create(
        document_type=DocumentType.RENT_CARD,
        content_type=ContentType.objects.get_for_model(tenancy),
        object_id=tenancy.pk,
        generated_by=generated_by,
    )
    document.file.save(f"rent_card_{tenancy.pk}_{timezone.now():%Y-%m-%d_%H-%M-%S}.pdf", ContentFile(pdf_bytes), save=True)
    return document


def generate_tenancy_agreement(agreement, generated_by=None):
    """
    Renders documents/tenancy_agreement_template.html into a PDF
    """
    context = {"agreement": agreement, "tenancy": agreement.tenancy, **_financial_display_context(agreement.tenancy)}
    pdf_bytes = _render_pdf("documents/tenancy_agreement_template.html", context)

    document = Document.objects.create(
        document_type=DocumentType.TENANCY_AGREEMENT,
        content_type=ContentType.objects.get_for_model(agreement),
        object_id=agreement.pk,
        generated_by=generated_by,
    )
    document.file.save(f"tenancy_agreement_{agreement.pk}_{timezone.now():%Y-%m-%d_%H-%M-%S}.pdf", ContentFile(pdf_bytes), save=True)
    return document


def generate_instalment_addendum(agreement, generated_by=None):
    """
    Generates the instalment addendum PDF for an Agreement, which is a formal
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
        f"instalment_addendum_{agreement.pk}_{timezone.now():%Y-%m-%d_%H-%M-%S}.pdf", ContentFile(pdf_bytes), save=True
    )
    return document


def generate_payment_receipt(payment, generated_by=None):
    """
    Act 220 Section 33 — payment receipts must be issued. Called
    automatically once a Payment is confirmed successful by
    payments.services._on_payment_success().
    """
    context = {"payment": payment, "tenancy": payment.tenancy}
    pdf_bytes = _render_pdf("documents/payment_receipt_template.html", context)

    document = Document.objects.create(
        document_type=DocumentType.PAYMENT_RECEIPT,
        content_type=ContentType.objects.get_for_model(payment),
        object_id=payment.pk,
        generated_by=generated_by,
    )
    document.file.save(f"receipt_{payment.pk}_{timezone.now():%Y-%m-%d_%H-%M-%S}.pdf", ContentFile(pdf_bytes), save=True)
    return document


def get_latest_document(obj, document_type):
    """
    Most recent Document of a given type for obj, or None. Needed now
    that RENT_CARD can have multiple snapshots per tenancy — use this
    wherever a template wants "the current one," e.g. the Agreement or
    Tenancy detail panel, rather than get_documents_for() which returns
    every snapshot.
    """
    return get_documents_for(obj).filter(document_type=document_type).first()


def get_documents_for(obj):
    """Return all Documents generic-FK'd to a given object (Tenancy, Agreement, ...)."""
    ct = ContentType.objects.get_for_model(obj)
    return Document.objects.filter(content_type=ct, object_id=obj.pk)


def generate_dispute_packet(tenancy, generated_by=None, dispute_summary=""):
    """
    Renders documents/dispute_packet_template.html into a PDF — a formal
    evidence packet covering the WHOLE tenancy (every maintenance
    request on it, plus the full negotiation history), suitable for
    submission to rent control or a court.
    """
    from apps.maintenance.models import MediaStage
    from apps.negotiations.services import get_proposal_chain
    
    try:
        if tenancy.status != TenancyStatus.ACTIVE:
            raise ValueError("This tenancy is not in active yet — a Dispute Packet is only available for active tenancies.")
    except ValueError as exc:
        raise ValueError(str(exc))

    maintenance_requests = tenancy.maintenance_requests.order_by("created_at")
 
    issues = []
    for index, maintenance_request in enumerate(maintenance_requests, start=1):
        issues.append({
            "index": index,
            "request": maintenance_request,
            "updates": maintenance_request.updates.all(),
            "reported_media": maintenance_request.media.filter(stage=MediaStage.REPORTED),
            "resolution_media": maintenance_request.media.filter(stage=MediaStage.RESOLUTION),
        })
 
    # Full negotiation history for the tenancy, oldest first.
    proposal_chain = get_proposal_chain(tenancy)
    packet_reference = f"DP-{str(tenancy.pk)[:8].upper()}-{timezone.now():%Y%m%d}"
 
    context = {
        "tenancy": tenancy,
        "issues": issues,
        "proposal_chain": proposal_chain,
        "generated_at": timezone.now(),
        "generated_by": generated_by,
        "dispute_summary": dispute_summary,
        "packet_reference": packet_reference,
        **_financial_display_context(tenancy),
    }
    pdf_bytes = _render_pdf("documents/dispute_packet_template.html", context)
 
    document = Document.objects.create(
        document_type=DocumentType.DISPUTE_PACKET,
        content_type=ContentType.objects.get_for_model(tenancy),
        object_id=tenancy.pk,
        generated_by=generated_by,
    )
    document.file.save(
        f"dispute_packet_{tenancy.pk}_{timezone.now():%Y-%m-%d_%H-%M-%S}.pdf",
        ContentFile(pdf_bytes),
        save=True,
    )
    return document

def generate_default_notice(tenancy, generated_by=None, cure_period_months=1):
    """
    Renders documents/default_notice_template.html into a PDF — a formal
    notice to the tenant regarding default on rent payments.
    """
    from dateutil.relativedelta import relativedelta
    from apps.payments.services import get_overdue_instalments, get_default_notice_eligible_instalments
 
    if not get_default_notice_eligible_instalments(tenancy):
        raise ValueError(
            "This tenancy has no instalment overdue beyond the reminder "
            "grace period — a Default Notice isn't available yet."
        )
 
    overdue_instalments = get_overdue_instalments(tenancy)
    total_owed = sum(row["amount"] for row in overdue_instalments)
 
    issued_at = timezone.now()
    cure_deadline = (issued_at + relativedelta(months=cure_period_months)).date()
 
    context = {
        "tenancy": tenancy,
        "overdue_instalments": overdue_instalments,
        "total_owed": total_owed,
        "issued_at": issued_at,
        "cure_deadline": cure_deadline,
        "cure_period_months": cure_period_months,
    }
    pdf_bytes = _render_pdf("documents/default_notice_template.html", context)
 
    document = Document.objects.create(
        document_type=DocumentType.DEFAULT_NOTICE,
        content_type=ContentType.objects.get_for_model(tenancy),
        object_id=tenancy.pk,
        generated_by=generated_by,
    )
    document.file.save(
        f"default_notice_{tenancy.pk}_{timezone.now():%Y-%m-%d_%H-%M-%S}.pdf",
        ContentFile(pdf_bytes),
        save=True,
    )
    return document