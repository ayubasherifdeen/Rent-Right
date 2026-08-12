"""
apps/payments/management/commands/send_payment_reminders.py

Run once a day, via a plain OS-level cron entry
 Example crontab line:

    0 8 * * * cd /path/to/project && venv/bin/python manage.py send_payment_reminders

Sends "due soon" (default: 3 days before due date) and "newly overdue"
(1 day after due date) SMS reminders. See send_instalment_reminders()
in apps/payments/services.py for the actual logic and the reasoning
behind the exact-day-match design.
"""

from django.core.management.base import BaseCommand

from apps.payments.services import send_instalment_reminders


class Command(BaseCommand):
    help = (
        "Sends 'due soon' and 'overdue' rent instalment SMS reminders "
        "across all active tenancies, plus a one-time landlord handoff "
        "notice once the overdue grace window expires. Meant to run "
        "once daily via cron, not interactively."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days-ahead",
            type=int,
            default=3,
            help="How many days before the due date to start sending 'due soon' reminders (default: 3).",
        )
        parser.add_argument(
            "--grace-days",
            type=int,
            default=3,
            help="How many days after the due date to keep sending daily overdue reminders before handing off to the landlord (default: 3).",
        )

    def handle(self, *args, **options):
        results = send_instalment_reminders(
            days_ahead=options["days_ahead"], grace_days=options["grace_days"]
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Sent {results['due_soon_sent']} due-soon, "
                f"{results['overdue_sent']} overdue, and "
                f"{results['handoff_sent']} landlord handoff reminders."
            )
        )
