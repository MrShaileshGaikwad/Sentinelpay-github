"""Create synthetic demo customers. The password comes from DEMO_PASSWORD and is never hard-coded."""
import os
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from banking.models import BankAccount, Beneficiary

DEMO_CUSTOMERS = [
    ("demo.customer1", "Asha", "Demo", 1),
    ("demo.customer2", "Ravi", "Demo", 2),
]


class Command(BaseCommand):
    help = "Create synthetic demo customers, accounts and beneficiaries."

    def handle(self, *args, **options):
        password = os.environ.get("DEMO_PASSWORD", "")
        if len(password) < 12:
            raise CommandError("Set DEMO_PASSWORD to at least 12 characters in the environment.")
        User = get_user_model()
        for username, first, last, n in DEMO_CUSTOMERS:
            user, created = User.objects.get_or_create(
                username=username, defaults={"first_name": first, "last_name": last}
            )
            if created:
                user.set_password(password)
                user.save()
            BankAccount.objects.get_or_create(
                account_ref=f"SYN-{n:08d}",
                defaults={"owner": user, "balance": Decimal("250000.00")},
            )
            Beneficiary.objects.get_or_create(
                owner=user,
                destination_ref=f"SYN-DEST-{n:06d}",
                defaults={"name": "Sample Utility Co"},
            )
        self.stdout.write("Demo customers are ready.")
