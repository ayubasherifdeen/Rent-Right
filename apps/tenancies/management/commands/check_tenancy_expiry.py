from django.core.management.base import BaseCommand
from apps.tenancies.services import check_tenancy_expiry


class Command(BaseCommand):
    help = (
        "Daily check: moves ACTIVE tenancies into EXPIRING near end_date, "
        "and EXPIRING/ACTIVE tenancies into ENDED at end_date. Notifies "
        "both parties either way."
    )

    def handle(self, *args, **options):
        counts = check_tenancy_expiry()
        self.stdout.write(
            self.style.SUCCESS(
                f"Expiring: {counts['expiring_marked']}, Ended: {counts['ended_marked']}"
            )
        )