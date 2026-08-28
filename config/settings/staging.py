"""
config/settings/staging.py

Staging environment on Railway.

Deliberately re-exports production.py wholesale rather than duplicating
its logic. production.py is already 100% environment-variable driven —
nothing in it is hardcoded to a specific database, domain, or key — so
"staging" and "production" only need to differ in WHICH values Railway
injects for DATABASE_URL, ALLOWED_HOSTS, PAYSTACK_*, etc, not in the
settings code itself.

This file exists purely so DJANGO_SETTINGS_MODULE can say
"config.settings.staging" instead of "config.settings.production" —
that distinction matters for anyone reading logs or a deploy dashboard
and needing to immediately know which environment they're looking at,
even though the Python behavior is identical.

Usage (set as a Railway service variable, not exported locally):
    DJANGO_SETTINGS_MODULE=config.settings.staging
"""
from .production import *  # noqa

# Intentionally empty beyond the import above. If staging ever needs to
# diverge from production's behavior (e.g. a different logging verbosity,
# or a staging-only feature flag), override it here explicitly — don't
# let this file silently drift into a full copy of production.py.
