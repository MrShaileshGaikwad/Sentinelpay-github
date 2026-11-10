from django.core.management.base import BaseCommand, CommandError
from django.db import connections


LEGACY_SYSTEM_TABLES = (
    "auth_group",
    "auth_group_permissions",
    "auth_permission",
    "auth_user",
    "auth_user_groups",
    "auth_user_user_permissions",
    "django_admin_log",
    "django_content_type",
    "django_migrations",
    "django_session",
)


class Command(BaseCommand):
    help = "Preserve MyBank's manually created Django-like tables under legacy names."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm-backup",
            action="store_true",
            help="Confirm that a verified database backup exists before renaming tables.",
        )
        parser.add_argument("--database", default="default")

    def handle(self, *args, **options):
        if not options["confirm_backup"]:
            raise CommandError(
                "Create and verify a MySQL backup, then rerun with --confirm-backup."
            )

        connection = connections[options["database"]]
        if connection.vendor != "mysql":
            raise CommandError("This command requires DB_ENGINE=mysql.")
        if connection.settings_dict["NAME"].lower() != "mybank":
            raise CommandError("Refusing to prepare a database other than mybank.")

        tables = set(connection.introspection.table_names())
        required_source_tables = {"customers", "accounts", "beneficiaries", "transactions"}
        missing_sources = required_source_tables - tables
        if missing_sources:
            raise CommandError(
                "MyBank source tables are missing: " + ", ".join(sorted(missing_sources))
            )

        rename_pairs = []
        for table in LEGACY_SYSTEM_TABLES:
            legacy_name = f"sentinelpay_legacy_{table}"
            if table in tables and legacy_name in tables:
                raise CommandError(
                    f"Both {table} and {legacy_name} exist; inspect the schema before retrying."
                )
            if table in tables:
                rename_pairs.append((table, legacy_name))

        if not rename_pairs:
            self.stdout.write("No manually created Django system tables need archiving.")
            return

        quote = connection.ops.quote_name
        statement = ", ".join(
            f"{quote(old)} TO {quote(new)}" for old, new in rename_pairs
        )
        with connection.cursor() as cursor:
            cursor.execute(f"RENAME TABLE {statement}")

        renamed = ", ".join(f"{old} -> {new}" for old, new in rename_pairs)
        self.stdout.write(self.style.SUCCESS(f"Preserved existing tables: {renamed}"))
        self.stdout.write(
            "Run `python manage.py migrate` next. The original customer, account, "
            "beneficiary, and transaction tables were not renamed or deleted."
        )
