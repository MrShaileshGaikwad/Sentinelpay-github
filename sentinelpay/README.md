# SentinelPay

SentinelPay is a synthetic digital-banking and payment-fraud demonstration built with Django. It does not connect to a bank or move real funds.

## Current features

- Customer sign-in, account overview, masked synthetic account references, and a six-month chart of successful payments based on stored payment records.
- Indian-banking-style customer profiles with customer-editable contact details, synthetic customer numbers, explicit unknown KYC/risk states, and account type/status plus separate available and ledger balances.
- Two-step payment experience: enter details, review the amount and source account, then confirm before server-side validation and screening.
- A persistent transaction record for each payment, linked to its source account and optional beneficiary, with the recorded status, risk score, reference, and processing time.
- Explicit payment state machine, deterministic sandbox gateway outcomes, idempotency protection, and synchronized account ledger balances only after a successful simulator response.
- Eight explainable, deterministic fraud rules with stored scores, decision, triggered reasons, and ruleset version. This is a rules engine, not a trained AI model or calibrated fraud probability.
- Append-only payment processing events displayed as a transaction timeline.
- Staff-only fraud monitoring and case review. Payments held or rejected by fraud policy create a review case; reviewers can assign themselves, update the case status, and record an audited note.
- Customer-scoped transaction history filters and a CSV statement whose debit column is derived from ledger postings.
- Responsive navy-and-teal workspace with account activity visualizations, payment progress and screening timelines, keyboard focus indicators, reduced-motion support, and a print-friendly payment receipt. Charts and risk indicators render persisted backend values.

## Project documents

- [Project flow](./docs/01-project-flow.md) — user journey from login through payment processing and logout.
- [Project structure](./docs/02-project-structure.md) — source tree, app responsibilities, and code organization rationale.
- [Software Requirements Specification](./docs/03-software-requirements-specification.md) — current functional/non-functional requirements and limitations.

## Page inventory

| Page | Route | Data and access |
| --- | --- | --- |
| Sign in | `/login/` | Django session authentication |
| Account overview | `/` | Current customer's profile, accounts, balances, and payment records |
| Customer profile | `/profile/` | Authenticated customer can edit their name, email, Indian mobile, date of birth, and address |
| Payment details and review | `/payments/new/`, `/payments/review/` | Server-validated payment draft, customer-owned account, eligible beneficiaries |
| Transaction history and statement | `/payments/`, `/payments/statement.csv` | Current customer's persisted payments and ledger debits |
| Payment receipt | `/payments/<reference>/` | Current customer's payment, fraud decision, audit timeline, and ledger records |
| Fraud intelligence and case review | `/payments/fraud/`, `/payments/fraud/cases/<id>/` | Staff or Fraud Analysts group only; persisted transactions, cases, and audit history |
| Django administration | `/admin/` | Django's built-in administration; access follows Django staff permissions |

There is no customer registration, general settings page, standalone audit-history route, real-time notification feed, or external payment/fraud API in this project. Payment receipts show the persisted payment event history, and fraud case detail shows audited case changes. The interface does not present simulator results as live banking activity. Decorative animation and chart motion use CSS only and are disabled for reduced-motion preferences.

The profile stores only details a user supplies. Customer numbers use the `SYN` prefix; missing date of birth, mobile, address, KYC, and risk-assessment information remain clearly marked as not provided or not assessed. The profile form does not collect Aadhaar or PAN. Existing account balances are preserved during migration; the initial ledger balance is set to that current balance as a cutover snapshot, not represented as a reconstructed historical statement. Existing payments are backfilled as transaction records from their persisted payment outcomes.

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

Open http://127.0.0.1:8000/ and sign in as `demo.customer1` with the password set in `DEMO_PASSWORD`. Keep the terminal open while the server is running. `seed_demo` creates synthetic demo users, customer profiles, accounts, and beneficiaries; it does not reset existing data.

Payment source accounts are only shown to their owning user. Signing in with a Django administrator account does not automatically give that account customer bank accounts; use one of the seeded demo customer accounts or link an account in Django administration. The beneficiary selector appears below the source account and lists active personal or project-wide beneficiaries. If none exist, merchant payments can still be made without a beneficiary.

Django reads configuration from process environment variables. A `.env` file is not automatically loaded. For a local-only demo, the settings have development defaults; use a unique secret key and `DJANGO_DEBUG=0` before any shared deployment. Configure `DJANGO_ALLOWED_HOSTS` and database environment variables explicitly when needed.

## Fraud analyst access

The fraud intelligence and case-review pages require either a Django staff account or membership in the `Fraud Analysts` group. A Django administrator can create that group and assign analyst users in `/admin/`. The server checks authorization on every protected view; hiding the navigation link is not the access control.

## Tests and checks

```powershell
python manage.py check
python -m pytest -v
```

Tests use SQLite. MySQL configuration exists but has not been verified in this environment.

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
