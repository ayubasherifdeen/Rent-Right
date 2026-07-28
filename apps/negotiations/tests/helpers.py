"""
ASSUMED INTERFACE, NOT CONFIRMED: imports apps.tenancies.tests.helpers.make_tenancy
for a base Tenancy fixture. I don't have that file for this session, so
its exact signature (kwargs accepted, defaults) is a guess based on how
it's described being used in handoff v8/v9. Adjust the import and call
below to match the real helper before trusting these tests.

Per the bug documented in v8 §2.10 / v9 §2.8 (a hardcoded default email
in make_tenancy() colliding when called bare from two tests in the same
TestCase), every call site below passes explicit, distinct emails —
never calls the factory bare.
"""
import itertools

from apps.negotiations.models import Proposal, ProposalStatus

_email_counter = itertools.count(1)


def unique_email(prefix="user"):
    return f"{prefix}{next(_email_counter)}@example.test"


def make_proposal(tenancy, proposed_by, previous_proposal=None, status=ProposalStatus.PENDING, **overrides):
    defaults = dict(
        tenancy=tenancy,
        previous_proposal=previous_proposal,
        proposed_by=proposed_by,
        status=status,
        advance_months=tenancy.advance_months,
        instalment_count=3,
        instalment_schedule=[
            {"due_date": "2026-08-01", "amount": "1000.00"},
            {"due_date": "2026-09-01", "amount": "1000.00"},
            {"due_date": "2026-10-01", "amount": "1000.00"},
        ],
    )
    defaults.update(overrides)
    return Proposal.objects.create(**defaults)
