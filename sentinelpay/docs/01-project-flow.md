# SentinelPay Project Flow

## Purpose and scope

This document describes the current browser-to-server flow in SentinelPay, from signing in through signing out. SentinelPay is a Django demonstration application: its account data is synthetic and payments use a deterministic local simulator. It does not connect to a bank or move real money.

## Application entry points

- Django starts through `manage.py` and loads settings from `sentinelpay/settings.py`.
- `sentinelpay/urls.py` routes the sign-in and sign-out endpoints, the customer overview, Django administration, and payment routes.
- Most customer pages require an authenticated Django user. Fraud operations additionally require a staff/superuser account or membership in the `Fraud Analysts` group.
- Django templates under `templates/` render the pages; `static/css/site.css` supplies the shared styles and CSS-only animations.

## End-to-end user journey

### 1. Open the application

The visitor opens `/`. The dashboard view is protected by Django's `login_required` decorator. If no authenticated session exists, Django redirects the visitor to `/login/`.

### 2. Sign in

The sign-in page uses Django's built-in `LoginView` with the SentinelPay login template. The browser submits the username and password over a CSRF-protected POST. Django checks the credentials and creates an authenticated session. Successful sign-in redirects to the configured dashboard (`LOGIN_REDIRECT_URL`); invalid credentials return the sign-in page with an error.

There is no public registration or password-reset workflow in the current routes. User accounts are managed by Django administration or project setup.

### 3. View the customer overview

The dashboard queries only records associated with the signed-in customer:

- Their own bank accounts and balances.
- Their payment counts, monthly successful spend, six-month payment activity, and recent transactions.
- A count of payments requiring attention.

The charts are rendered from these database results. They are not an independent source of transaction data. Account references are masked in the customer-facing view.

### 4. Start a payment

The customer opens `/payments/new/`. The form offers:

- Source accounts owned by that customer.
- That customer's own beneficiaries and project-wide beneficiaries.
- A positive decimal amount and one of the configured simulator routes.
- A generated idempotency key retained as a hidden form field.

Django validates the submitted values against server-side form fields and querysets. Another customer's private account or beneficiary is not an eligible choice. A valid form does not create or debit a payment: it stores a short-lived payment draft in the customer's session and redirects to review.

### 5. Review the payment

At `/payments/review/`, the server reconstructs and validates the form from the session draft. If the saved details are missing or no longer valid, the draft is removed and the customer is asked to restart. The review shows the amount, source account, recipient, masked beneficiary destination when present, and the selected simulator route.

The customer may edit the details, cancel, or confirm. Cancelling removes the draft without creating a payment. Confirming sends a CSRF-protected POST. The review page does not decide the fraud result or payment outcome.

### 6. Server-side processing and fraud evaluation

On confirmation, `payments.views.payment_review` calls `payments.services.create_payment`. The service performs the authoritative checks and processing:

1. Validates the amount and configured merchant code.
2. Creates a request fingerprint and checks the customer's idempotency key. An identical retry returns the original payment; a different request using the same key is rejected.
3. Within a database transaction, looks up the source account while verifying ownership.
4. Looks up the beneficiary while allowing only the customer's own or project-wide beneficiary.
5. Checks the available account balance.
6. Builds a fraud context from persisted payment history, the beneficiary creation time, amount, and local time.
7. Calls the existing deterministic rules engine in `fraud_engine/engine.py`.
8. Persists the payment with the evaluated score, decision, triggered-rule explanations, and ruleset version, and appends processing events through the audit service.

The eight rule results and the decision thresholds are documented in the project README. They are educational rule points, not calibrated fraud probabilities. Device and IP-country rules are inactive because the application does not collect those signals.

### 7. Apply the fraud decision and simulator outcome

The backend enforces the result before submission:

- `DECLINE` becomes `REJECTED`; no simulator request or ledger debit is made.
- `REVIEW` and `STEP_UP` become `HELD_FOR_REVIEW`; no debit is made and a fraud case is created. The step-up challenge flow is not implemented.
- An approved payment becomes `SUBMITTED` and is passed to `payments.gateway.SimulatedGateway`. The simulator's selected route determines the outcome.

| Simulator route | Recorded outcome | Debit behavior |
| --- | --- | --- |
| `SIM-GROCERY` | `SUCCEEDED` | A ledger debit is posted once if the balance update succeeds. |
| `SIM-DECLINE` | `FAILED` | No debit. |
| `SIM-TIMEOUT` | `UNKNOWN` | No debit; no automatic retry or reconciliation workflow. |
| `SIM-ERROR` | `FAILED` | No debit. |

All status changes use the state transition function in `payments/states.py`. The database constraints and transactional service protect idempotency and ledger posting.

### 8. View the result

After processing, the browser is redirected to the payment receipt identified by a unique public reference. The receipt is scoped to the signed-in customer and displays the persisted payment status, amount, account, recipient, fraud score and decision, triggered rules, recorded audit timeline, and any ledger entry.

The timeline is read from stored audit events. Its animation is a presentation effect; it does not imply that the transaction is still processing. The risk meter uses the stored score rather than inventing a new value.

### 9. Review fraud cases (authorized users only)

Staff, superusers, and members of the `Fraud Analysts` group can open `/payments/fraud/` and `/payments/fraud/cases/<id>/`. The monitoring page queries persisted payment and case records. Authorized reviewers may update a case through allowed status transitions and add a note. Each accepted change records the reviewer, old and new statuses, note, timestamp, and payment correlation ID in the append-only audit log.

Customer users who do not meet the server-side permission check receive HTTP 403 even if they manually enter a fraud route.

### 10. Sign out

The shared navigation submits a CSRF-protected POST to `/logout/`. Django's built-in `LogoutView` ends the authenticated session and redirects according to Django's logout behavior. The user must sign in again to access protected pages.

## Data and configuration flow

- SQLite is the default database, stored at the project root as `db.sqlite3`.
- Setting `DB_ENGINE=mysql` switches settings to the configured MySQL environment variables. MySQL is optional and has not been verified as part of the current setup.
- Credentials and settings are read from process environment variables. `.env.example` contains placeholders; Django does not automatically load a `.env` file.
- `python manage.py migrate` applies schema migrations. This document does not imply that a migration has already been applied to a particular local database.

## Current flow limitations

- Payments are simulated; no real payment network or provider is contacted.
- There is no public registration, custom account-management page, live transaction feed, or external fraud API.
- Unknown gateway outcomes remain unresolved until a future reconciliation feature exists.
- Payment limits, fees, step-up authentication, and customer-managed beneficiary creation are not implemented.
