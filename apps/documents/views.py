"""
documents/views.py

Single endpoint: download a Document if the requesting user is a party
to whatever the Document is attached to.

Tenancy.landlord / .tenant confirmed against the real create_tenancy()
in apps/tenancies/services.py. Agreement.tenancy (OneToOne) confirmed
per handoff v8 §2.2, so access for an Agreement-attached Document is
resolved via agreement.tenancy.landlord / .tenant.

If a document_type is later attached to some other model, add a branch
to `_resolve_tenancy` below rather than assuming every content_object
either IS a Tenancy or HAS a .tenancy.
"""

from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404

from .models import Document


def _resolve_tenancy(content_object):
    if hasattr(content_object, "tenancy"):
        return content_object.tenancy
    return content_object


def _user_can_access(user, document):
    tenancy = _resolve_tenancy(document.content_object)
    if user.is_staff:
        return True
    return user == getattr(tenancy, "landlord", None) or user == getattr(tenancy, "tenant", None)


@login_required
def download_document(request, document_id):
    document = get_object_or_404(Document, pk=document_id)
    if not _user_can_access(request.user, document):
        # 404, not 403 — don't confirm existence of documents belonging
        # to other parties. Matches the access-control pattern used for
        # agreement_detail in the tenancies app (v8 §2.10, "a stranger
        # requesting another party's agreement").
        raise Http404("Document not found.")

    return FileResponse(
        document.file.open("rb"),
        as_attachment=True,
        filename=document.file.name.rsplit("/", 1)[-1],
    )
