# SentinelPay

SentinelPay is a synthetic digital-banking and payment-fraud demonstration built with Django. It does not connect to a bank or move real funds.

## Current features

- Customer sign-in, account overview, masked synthetic account references, and a six-month chart of successful payments based on stored payment records.
- Public customer registration with username/password authentication, a linked customer profile, and a clearly synthetic savings account with an INR 250,000.00 demo starting balance; no real bank account is opened or linked.
- Indian-banking-style customer profiles with customer-editable contact details, synthetic customer numbers, explicit unknown KYC/risk states, and account type/status plus separate available and ledger balances.
- Two-step payment experience: enter details, review the amount and source account, then confirm before server-side validation and screening.
- A persistent transaction record for each payment, linked to its source account and optional beneficiary, with the recorded status, risk score, reference, and processing time.
- Timezone-aware transaction creation/completion timestamps, monotonic processing-duration measurements, and append-only audit events for transaction creation, status transitions, fraud decisions, and processing completion.
- An authenticated, customer-scoped recent-transactions JSON endpoint and dashboard polling monitor (5-second default; configurable with `TRANSACTION_MONITOR_POLL_INTERVAL_MS`) that reports loading and refresh errors.
- Explicit payment state machine, deterministic sandbox gateway outcomes, idempotency protection, and synchronized account ledger balances only after a successful simulator response.
- Eight explainable, deterministic fraud rules with stored scores, decision, triggered reasons, and ruleset version. This is a rules engine, not a trained AI model or calibrated fraud probability.
- Append-only payment processing events displayed as a transaction timeline.
- Staff-only fraud monitoring and case review. Payments held or rejected by fraud policy create a review case; reviewers can assign themselves, update the case status, and record an audited note.
- Customer-scoped payment history and CSV statement, plus transaction history including clearly labelled imported MyBank activity.
- Responsive navy-and-teal workspace with account activity visualizations, payment progress and screening timelines, keyboard focus indicators, reduced-motion support, and a print-friendly payment receipt. Charts and risk indicators render persisted backend values.

## Project documents

- [Project flow](./docs/01-project-flow.md) — user journey from login through payment processing and logout.
- [Project structure](./docs/02-project-structure.md) — source tree, app responsibilities, and code organization rationale.
- [Software Requirements Specification](./docs/03-software-requirements-specification.md) — current functional/non-functional requirements and limitations.
- [Project walkthrough and demo guide](./docs/04-project-presentation-and-demo-guide.md) — architecture and lifecycle diagrams, presentation setup, timed demo script, and likely questions.

## Page inventory

| Page | Route | Data and access |
| --- | --- | --- |
| Sign in | `/login/` | Django session authentication |
| Create account | `/register/` | Public; creates a SentinelPay user and customer profile |
| Account overview | `/` | Current customer's profile, accounts, balances, and payment records |
| Customer profile | `/profile/` | Authenticated customer can edit their name, email, Indian mobile, date of birth, and address |
| Payment details and review | `/payments/new/`, `/payments/review/` | Server-validated payment draft, customer-owned account, eligible beneficiaries |
| Payment history and statement | `/payments/`, `/payments/statement.csv` | Current customer's persisted payments and ledger debits |
| Transaction history | `/transactions/` | Current customer's simulator and imported transaction records |
| Recent transactions API | `/api/transactions/recent/` | Authenticated JSON feed scoped to accounts owned by the signed-in customer |
| Payment receipt | `/payments/<reference>/` | Current customer's payment, fraud decision, audit timeline, and ledger records |
| Fraud intelligence and case review | `/payments/fraud/`, `/payments/fraud/cases/<id>/` | Staff or Fraud Analysts group only; persisted transactions, cases, and audit history |
| Django administration | `/admin/` | Django's built-in administration; access follows Django staff permissions |

There is no email verification, self-service password reset, general settings page, standalone audit-history route, real-time notification feed, or external payment/fraud API in this project. Public registration creates a SentinelPay login and customer profile only; it does not open or connect a real bank account. Payment receipts show the persisted payment event history, and fraud case detail shows audited case changes. The interface does not present simulator results as live banking activity. Decorative animation and chart motion use CSS only and are disabled for reduced-motion preferences.

The profile stores only details a user supplies. Customer numbers use the `SYN` prefix; missing date of birth, mobile, address, KYC, and risk-assessment information remain clearly marked as not provided or not assessed. The profile form does not collect Aadhaar or PAN. Existing account balances are preserved during migration; the initial ledger balance is set to that current balance as a cutover snapshot, not represented as a reconstructed historical statement. Existing payments are backfilled as transaction records from their persisted payment outcomes.

The dashboard polls the recent transaction API every 5 seconds by default. Set `TRANSACTION_MONITOR_POLL_INTERVAL_MS` to another positive millisecond interval to configure it. Transaction processing duration uses a monotonic timer; database timestamps are timezone-aware. Historical rows retain a null duration because old elapsed times cannot be reconstructed. Audit metadata contains lifecycle statuses, fraud score/decision/ruleset, and duration only; it excludes credentials, tokens, and account/payment payloads.

Each developer's SQLite database is local to that machine. Usernames, passwords, admin permissions, profiles, and accounts are database records and are not copied when the source code is copied. An empty payment account selector means the signed-in user has no active account in the currently configured database; demo accounts created by `seed_demo` belong to `demo.customer1` and `demo.customer2`, not to another user.

## Demonstration fraud policy

Scores are the capped sum of these rule weights. They are explainable rule points, not probabilities:

| Rule | Trigger | Points |
| --- | --- | ---: |
| R-01 | Amount is at least 100,000 currency units (demo accounts use INR) | 30 |
| R-02 | Amount is at least 3 times the source account's successful 30-day average | 20 |
| R-03 | At least 5 earlier payment attempts occurred in the previous hour | 15 |
| R-04 | At least 3 failed or rejected attempts occurred in the previous hour | 20 |
| R-05 | Beneficiary was added within the previous 24 hours | 15 |
| R-06 | Payment initiated from 00:00 through 04:59 local time | 10 |
| R-07 | New device | 15 (inactive; device data is not collected) |
| R-08 | IP country differs from home country | 15 (inactive; IP-country data is not collected) |

Scores 0–29 are approved, 30–49 require step-up, 50–79 are held for review, and 80–100 are declined. Step-up is not implemented, so step-up decisions are also held without a debit. These thresholds are fixed educational policy and must not be treated as production banking controls.

## Run locally (Windows PowerShell)

From the project directory:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:DJANGO_SECRET_KEY = "replace-with-a-local-development-secret"
$env:DEMO_PASSWORD = "choose-a-12+-character-password"
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

Open http://127.0.0.1:8000/ and sign in as `demo.customer1` with the password set in `DEMO_PASSWORD`. Keep the terminal open while the server is running. `seed_demo` creates synthetic demo users, customer profiles, accounts, and beneficiaries; it does not reset existing data or change passwords for existing users. Use `python manage.py changepassword <username>` to reset an existing account password. Use `python manage.py createsuperuser` to create an administrator; demo customers are not administrators.

Payment source accounts are only shown to their owning user. Signing in with a Django administrator account does not automatically give that account customer bank accounts; use one of the seeded demo customer accounts or link an account in Django administration. The beneficiary selector appears below the source account and lists active personal or project-wide beneficiaries. If none exist, merchant payments can still be made without a beneficiary.

Django reads configuration from process environment variables and the optional, git-ignored `.env` file. To use MySQL, copy `.env.example` to `.env`, set `DB_PASSWORD` to your local MySQL password, and set `DB_NAME` to a new or intentionally selected schema. Keep credentials local and never put them in `.env.example`. Start MySQL Server, then use `python manage.py migrate` and `python manage.py runserver` from the `sentinelpay` directory. MySQL is only used when `DB_ENGINE=mysql`; otherwise SentinelPay continues to use SQLite. Changing the database setting does not copy existing SQLite records; export/import application data separately, and do not load a fixture into populated tables without checking for primary-key conflicts. For a local-only demo, the settings have development defaults; use a unique secret key and `DJANGO_DEBUG=0` before any shared deployment. Configure `DJANGO_ALLOWED_HOSTS` and database environment variables explicitly when needed.
The MyBank import procedure below is the supported path for importing that existing schema; do not run plain Django migrations against it before preparing the conflicting system tables.

## Fraud analyst access

The fraud intelligence and case-review pages require either a Django staff account or membership in the `Fraud Analysts` group. A Django administrator can create that group and assign analyst users in `/admin/`. The server checks authorization on every protected view; hiding the navigation link is not the access control.

## Use the existing MyBank MySQL database

SQLite remains the default. To use the existing local MySQL database named `mybank`, configure `DB_ENGINE=mysql` and `DB_NAME=mybank`. This project preserves the original `customers`, `accounts`, `beneficiaries`, and `transactions` tables and imports their records into SentinelPay's Django-managed tables. Do not point Django at `mybank` and migrate before completing the backup and preparation steps below: its manually created `auth_*` and `django_*` tables conflict with Django's schema.

The legacy `transactions` source table relates a transaction to an account through `account_id`; it has no direct customer foreign key. The importer resolves ownership through `transactions.account_id → accounts.account_id → accounts.customer_id → customers.customer_id` and maps into Django's separate `banking_transaction` table, whose `account` foreign key leads to an account owned by a Django user. It does not alter the legacy table or infer a new customer column.

1. Install the MySQL driver and make a full backup **before changing any MySQL schema**. From PowerShell:

   ```powershell
   pip install -r requirements-mysql.txt
   $backup = Join-Path $env:USERPROFILE "mybank-before-sentinelpay.sql"
   & "C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe" --user=root --host=127.0.0.1 --databases mybank --result-file=$backup --password
   if ($LASTEXITCODE -ne 0 -or !(Test-Path $backup) -or (Get-Item $backup).Length -eq 0) { throw "MyBank backup failed; do not continue." }
   Select-String -Path $backup -Pattern "CREATE TABLE|INSERT INTO" | Select-Object -First 10
   ```

   Enter the root password only at the client prompt. Keep the backup outside the repository, verify it contains schema and data, and retain it safely. Never put a password in a command, script, `.env.example`, or Git.

2. In MySQL Workbench or the MySQL client, create a dedicated local application account with access to the existing database (do not use `root` in the application):

   ```sql
   CREATE USER 'sentinelpay_app'@'127.0.0.1' IDENTIFIED BY 'choose-a-unique-local-password';
   GRANT ALL PRIVILEGES ON mybank.* TO 'sentinelpay_app'@'127.0.0.1';
   ```

   If that MySQL account already exists, alter its password rather than creating a duplicate. Keep MySQL restricted to trusted local/private network connections.

3. Copy `.env.example` to `.env` in the `sentinelpay` project directory. Replace the placeholder `DJANGO_SECRET_KEY` with a long random local secret, then set `DB_ENGINE=mysql`, `DB_NAME=mybank`, `DB_USER=sentinelpay_app`, `DB_PASSWORD` to the application user's password, `DB_HOST=127.0.0.1`, and `DB_PORT=3306`. Keep `.env` private; it is ignored by Git. Check that Django is connected to the intended database before continuing:

   ```powershell
   python manage.py shell -c "from django.db import connection; connection.ensure_connection(); print('Database:', connection.vendor, connection.settings_dict['NAME'])"
   ```

4. Only after the backup is verified, preserve the incompatible Django-like tables by renaming them (the command refuses other databases and does not touch the four banking source tables), then migrate:

   ```powershell
   python manage.py prepare_mybank --confirm-backup
   python manage.py migrate
   python manage.py createsuperuser
   python manage.py import_mybank_legacy
   ```

   `prepare_mybank` renames existing `auth_*` and `django_*` tables to `sentinelpay_legacy_*`; it does not delete them. The import command is repeat-safe and retains the source tables. Imported accounts retain the source balance as both available and ledger-balance cutover snapshots; historical transactions are labeled as imported and do not recalculate balances. Imported customer accounts receive no usable password. Create the administrator interactively with `createsuperuser`; an administrator can later provision customer passwords through Django admin. Do not run `seed_demo` against `mybank` unless you explicitly want extra synthetic users and records.

`DB_ENGINE` must be `sqlite` or `mysql`; invalid values and missing MySQL settings fail explicitly instead of silently falling back to SQLite. For another developer's computer, configure the same authorized MySQL server/database; `127.0.0.1` always means that developer's own computer.

## Differences between computers

The database controls account/user records, but it does not control CSS. Compare `git rev-parse --short HEAD` on each computer and update both to the same branch/commit. The workspace intentionally combines a dark navigation rail with light content panels. After updating, restart Django and hard-refresh the browser with Ctrl+F5; the stylesheet URL version is bumped to invalidate cached CSS. If the same commit still renders differently, compare browser viewport/zoom and confirm that both run the same checkout and static files.

## Tests and checks

```powershell
python manage.py check
python -m pytest -v
```

Tests always use an isolated SQLite test database, even when the local `.env` selects MySQL. The active configuration in the inspected workspace used the local `sentinelpay/db.sqlite3`; no MySQL migration or import was run. MySQL schema preparation/import is an explicit separate operation and has not been verified end to end.
Automated tests use an isolated SQLite database. The local MySQL connection was inspected separately; the MyBank legacy schema preparation/import has not been verified end to end.

## Optional VS Code Git auto-sync

When the repository folder is trusted and opened in VS Code, the task in the repository-root `.vscode/tasks.json` starts `sentinelpay/scripts/auto-sync.ps1`. After saved or staged changes remain unchanged for five seconds, the watcher stages them, creates a commit, and pushes them to the current branch's configured upstream. This can publish unfinished work; stop the task with Ctrl+C or disable the folder-open task if you prefer manual review.

GitHub authentication must already work through Git Credential Manager or VS Code's GitHub sign-in. The watcher does not store credentials. It refuses to auto-commit `.env` files (except `.env.example`), database files, private-key files, and names matching common secret/credential patterns. Existing `.gitignore` exclusions still apply. If the remote is ahead, it will not rebase or rewrite history; sync the branch manually before resuming. Git/commit failures are shown in the task terminal, and local work is preserved.

## Demonstration payment outcomes

The merchant code selects the simulator response:

| Merchant | Outcome |
| --- | --- |
| `SIM-GROCERY` | Success |
| `SIM-DECLINE` | Decline |
| `SIM-TIMEOUT` | Unknown outcome; no automatic retry or debit |
| `SIM-ERROR` | Failure |

Fraud decisions are enforced before the simulator call. Held and rejected payments do not post a ledger debit. Successful payments create one negative ledger entry and reduce the source account balance once.

## Scope and limitations

- The account data and gateway are synthetic; there are no real transfers, inbound payments, fees, or payment-provider integrations. Transaction records reflect the local simulator outcome only.
- The fraud rules and thresholds are fixed demonstration policy. Device/IP rules remain inactive because this app does not collect those signals.
- Step-up authentication, payment reconciliation for unknown gateway outcomes, double-entry accounting, analyst case escalation notifications, PDF statements, real-time push updates, and production MySQL verification are not implemented.
- Review cases are automatically created for held/rejected fraud decisions. The case workflow supports new, investigating, escalated, resolved, and false-positive states with audited updates.
- Beneficiaries can be customer-owned or project-wide. Project-wide entries are available to every customer and can be created in Django admin by leaving the owner blank; `seed_demo` creates a shared sample utility beneficiary. Beneficiaries do not yet have a customer-facing management screen.
- Customer KYC and risk values are status placeholders, not identity verification or a customer risk assessment. Account and transaction data does not represent a real bank account or bank-issued record.
- Statements include requested amounts and ledger-backed debits; they are not bank-issued statements.
- External web fonts are not required. Bootstrap styling is implemented locally in the project stylesheet.
