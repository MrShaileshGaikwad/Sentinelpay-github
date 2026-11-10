"""Create synthetic demo customers. The password comes from DEMO_PASSWORD and is never hard-coded."""
import os
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from banking.models import BankAccount, Beneficiary, Customer

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
        Beneficiary.objects.get_or_create(
            owner=None,
            destination_ref="SYN-DEST-000000",
            defaults={"name": "Sample Utility Co"},
        )
        for username, first, last, n in DEMO_CUSTOMERS:
            user, created = User.objects.get_or_create(
                username=username, defaults={"first_name": first, "last_name": last}
            )
            if created:
                user.set_password(password)
                user.save()
            Customer.objects.get_or_create(
                user=user,
                defaults={
                    "first_name": first,
                    "last_name": last,
                    "email": user.email,
                },
            )
            BankAccount.objects.get_or_create(
                account_ref=f"SYN-{n:08d}",
                defaults={
                    "owner": user,
                    "account_type": BankAccount.AccountType.SAVINGS,
                    "balance": Decimal("250000.00"),
                    "ledger_balance": Decimal("250000.00"),
                    "account_status": BankAccount.AccountStatus.ACTIVE,
                },
            )
        self.stdout.write("Demo customers are ready.")
