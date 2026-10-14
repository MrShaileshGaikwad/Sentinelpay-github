# SentinelPay (vertical slice)

Simulated digital banking with card-payment fraud checks. Synthetic data only. No real funds move.

## What this slice contains
- Login/logout, responsive dashboard, own-account balances, and paginated customer-scoped payment history.
- Payment form: own accounts and beneficiaries only, idempotency key, server-side validation.
- Payment lifecycle with an explicit state machine (`payments/states.py`).
- Deterministic fraud engine with 8 rules (`fraud_engine/engine.py`). R-07 and R-08 are inactive in this slice because no device or IP data is captured.
- Sandbox gateway simulator (`payments/gateway.py`). Merchant code selects the outcome: SIM-GROCERY success, SIM-DECLINE decline, SIM-TIMEOUT unknown, SIM-ERROR failure.
- Append-only audit events and ledger entries with database constraints.

## Not in this slice (see the scope notes in the design documents)
Step-up authentication challenge, analyst case workflow, reconciliation, DRF API, notifications, MySQL verification, Docker, CI.

## Run it (Windows PowerShell, from the project folder)
```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env        # then edit values; the app reads them from the environment
$env:DEMO_PASSWORD = "choose-a-12+-char-password"
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```
Log in as `demo.customer1` with the password you set. Pytest uses SQLite, so MySQL is not needed for tests.

## Run tests
```powershell
python -m pytest -v
```

## Limitations
- Development settings: DEBUG defaults to on. Set `DJANGO_DEBUG=0` and a real secret key before any shared deployment.
- Bootstrap is loaded from a CDN, so the page needs internet access to look right.
- The MySQL path is configured but not yet verified in this environment.
