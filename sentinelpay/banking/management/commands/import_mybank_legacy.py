from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from banking.models import BankAccount, Beneficiary, Customer, Transaction


class Command(BaseCommand):
    help = (
        "Import customers, accounts, beneficiaries, and historical activity "
        "from the existing MyBank tables."
    )

    def handle(self, *args, **options):
        from django.db import connection

        if connection.vendor != "mysql":
            raise CommandError("This import command requires DB_ENGINE=mysql.")

        required_tables = {"customers", "accounts", "beneficiaries", "transactions"}
        missing_tables = required_tables - set(connection.introspection.table_names())
        if missing_tables:
            raise CommandError(
                "Missing MyBank source tables: " + ", ".join(sorted(missing_tables))
            )

        User = get_user_model()
        user_by_customer_id = {}
        counts = {"customers": 0, "accounts": 0, "beneficiaries": 0, "transactions": 0}

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT customer_id, full_name, email, phone FROM customers ORDER BY customer_id"
                )
                customer_rows = cursor.fetchall()
                cursor.execute(
                    "SELECT account_id, customer_id, account_number, balance, account_type "
                    "FROM accounts ORDER BY account_id"
                )
                account_rows = cursor.fetchall()
                cursor.execute(
                    "SELECT beneficiary_id, customer_id, beneficiary_name, account_number, bank_name "
                    "FROM beneficiaries ORDER BY beneficiary_id"
                )
                beneficiary_rows = cursor.fetchall()
                cursor.execute(
                    "SELECT transaction_id, account_id, amount, transaction_type, "
                    "transaction_status, transaction_date FROM transactions ORDER BY transaction_id"
                )
                transaction_rows = cursor.fetchall()

            for customer_id, full_name, email, phone in customer_rows:
                first_name, _, last_name = (full_name or "").strip().partition(" ")
                username = f"mybank_customer_{customer_id}"
                user, _ = User.objects.get_or_create(
                    username=username,
                    defaults={
                        "first_name": first_name[:150],
                        "last_name": last_name[:150],
                        "email": (email or "")[:254],
                        "is_active": True,
                    },
                )
                if not user.has_usable_password():
                    user.set_unusable_password()
                    user.save(update_fields=["password"])
                profile, created = Customer.objects.get_or_create(
                    user=user,
                    defaults={
                        "first_name": first_name[:100],
                        "last_name": last_name[:100],
                        "email": (email or "")[:254],
                        "phone_number": (phone or "")[:20],
                    },
                )
                if created:
                    counts["customers"] += 1
                user_by_customer_id[customer_id] = user

            for account_id, customer_id, account_number, balance, account_type in account_rows:
                owner = user_by_customer_id.get(customer_id)
                if owner is None:
                    raise CommandError(
                        f"Account {account_id} refers to missing MyBank customer {customer_id}."
                    )
                account_type_key = (account_type or "").strip().upper().replace(" ", "_")
                if account_type_key not in BankAccount.AccountType.values:
                    account_type_key = BankAccount.AccountType.UNSPECIFIED
                account_balance = Decimal(balance)
                account, created = BankAccount.objects.get_or_create(
                    pk=account_id,
                    defaults={
                        "owner": owner,
                        "account_ref": account_number,
                        "account_type": account_type_key,
                        "currency": "INR",
                        "balance": account_balance,
                        "ledger_balance": account_balance,
                        "account_status": BankAccount.AccountStatus.ACTIVE,
                    },
                )
                if not created and (
                    account.owner_id != owner.pk or account.account_ref != account_number
                ):
                    raise CommandError(
                        f"Bank account ID {account_id} already belongs to a different record."
                    )
                if created:
                    counts["accounts"] += 1

            for beneficiary_id, customer_id, name, destination, bank_name in beneficiary_rows:
                owner = user_by_customer_id.get(customer_id)
                if owner is None:
                    raise CommandError(
                        f"Beneficiary {beneficiary_id} refers to missing MyBank customer {customer_id}."
                    )
                beneficiary, created = Beneficiary.objects.get_or_create(
                    pk=beneficiary_id,
                    defaults={
                        "owner": owner,
                        "name": name[:150],
                        "destination_ref": destination[:34],
                        "bank_name": (bank_name or "")[:100],
                        "verification_status": Beneficiary.VerificationStatus.NOT_VERIFIED,
                        "is_active": True,
                    },
                )
                if not created and (
                    beneficiary.owner_id != owner.pk
                    or beneficiary.destination_ref != destination[:34]
                ):
                    raise CommandError(
                        f"Beneficiary ID {beneficiary_id} already belongs to a different record."
                    )
                if created:
                    counts["beneficiaries"] += 1

            status_map = {
                "SUCCESS": Transaction.Status.SUCCEEDED,
                "SUCCEEDED": Transaction.Status.SUCCEEDED,
                "PENDING": Transaction.Status.PENDING,
                "FAILED": Transaction.Status.FAILED,
            }
            for transaction_id, account_id, amount, transaction_type, status, created_at in transaction_rows:
                account = BankAccount.objects.filter(pk=account_id).first()
                if account is None:
                    raise CommandError(
                        f"Transaction {transaction_id} refers to missing MyBank account {account_id}."
                    )
                type_key = (transaction_type or "").strip().upper()
                if type_key not in Transaction.Type.values:
                    raise CommandError(
                        f"Transaction {transaction_id} has unsupported type {type_key!r}."
                    )
                status_key = status_map.get((status or "").strip().upper())
                if status_key is None:
                    raise CommandError(
                        f"Transaction {transaction_id} has unsupported status {status!r}."
                    )
                if timezone.is_naive(created_at):
                    created_at = timezone.make_aware(created_at, timezone.get_current_timezone())
                _, created = Transaction.objects.get_or_create(
                    pk=transaction_id,
                    defaults={
                        "payment": None,
                        "account": account,
                        "transaction_type": type_key,
                        "description": f"Imported MyBank {type_key.lower()}",
                        "amount": Decimal(amount),
                        "currency": "INR",
                        "transaction_status": status_key,
                        "channel": "LEGACY_IMPORT",
                        "risk_score": Decimal("0.00"),
                        "created_at": created_at,
                        "processed_at": created_at if status_key != Transaction.Status.PENDING else None,
                    },
                )
                if created:
                    counts["transactions"] += 1

        self.stdout.write(
            self.style.SUCCESS(
                "MyBank import complete: "
                + ", ".join(f"{count} {kind}" for kind, count in counts.items())
                + ". Imported customer logins have no password; an administrator "
                "must set passwords before customers can sign in."
            )
        )
