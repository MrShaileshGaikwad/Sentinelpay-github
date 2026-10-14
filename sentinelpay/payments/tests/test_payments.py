from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditEvent
from banking.models import BankAccount, Beneficiary
from payments.models import LedgerEntry, Payment
from payments.services import IdempotencyConflict, InsufficientFunds, PaymentError, create_payment
from payments.states import InvalidTransition, transition


# Fixed evaluation time (14:00 IST) so the night-time rule never depends on the real clock.
NOON = timezone.make_aware(datetime(2026, 10, 17, 14, 0))


def pay(customer, account, beneficiary=None, amount="500.00", merchant="SIM-GROCERY", key="key-1", now=NOON):
    return create_payment(
        customer=customer,
        account_id=account.pk,
        beneficiary_id=beneficiary.pk if beneficiary else None,
        amount=Decimal(amount),
        merchant_code=merchant,
        idempotency_key=key,
        now=now,
    )


def balance(account):
    account.refresh_from_db()
    return account.balance


@pytest.mark.django_db
def test_successful_payment_debits_once_and_records_ledger(customer, account, old_beneficiary):
    p = pay(customer, account, old_beneficiary)
    assert p.status == Payment.Status.SUCCEEDED
    assert p.gateway_code == "SIM_SUCCESS"
    assert balance(account) == Decimal("249500.00")
    assert LedgerEntry.objects.filter(payment=p).count() == 1
    assert LedgerEntry.objects.get(payment=p).amount == Decimal("-500.00")


@pytest.mark.django_db
def test_fraud_result_is_stored_with_ruleset_version(customer, account, old_beneficiary):
    p = pay(customer, account, old_beneficiary)
    assert p.fraud_score == 0
    assert p.fraud_decision == "APPROVE"
    assert p.fraud_ruleset_version == "1.0.0"


@pytest.mark.django_db
def test_same_key_same_request_returns_original_without_second_debit(customer, account, old_beneficiary):
    first = pay(customer, account, old_beneficiary)
    second = pay(customer, account, old_beneficiary)
    assert first.pk == second.pk
    assert Payment.objects.count() == 1
    assert balance(account) == Decimal("249500.00")


@pytest.mark.django_db
def test_same_key_different_request_is_rejected(customer, account, old_beneficiary):
    pay(customer, account, old_beneficiary, amount="500.00")
    with pytest.raises(IdempotencyConflict):
        pay(customer, account, old_beneficiary, amount="600.00")
    assert balance(account) == Decimal("249500.00")


@pytest.mark.django_db
def test_gateway_decline_does_not_debit(customer, account, old_beneficiary):
    p = pay(customer, account, old_beneficiary, merchant="SIM-DECLINE")
    assert p.status == Payment.Status.FAILED
    assert p.gateway_code == "SIM_DECLINED"
    assert balance(account) == Decimal("250000.00")
    assert not LedgerEntry.objects.filter(payment=p).exists()


@pytest.mark.django_db
def test_gateway_timeout_is_unknown_not_success_and_retry_does_not_debit(customer, account, old_beneficiary):
    p = pay(customer, account, old_beneficiary, merchant="SIM-TIMEOUT", key="timeout-1")
    assert p.status == Payment.Status.UNKNOWN
    assert balance(account) == Decimal("250000.00")
    retry = pay(customer, account, old_beneficiary, merchant="SIM-TIMEOUT", key="timeout-1")
    assert retry.pk == p.pk
    assert retry.status == Payment.Status.UNKNOWN
    assert balance(account) == Decimal("250000.00")


@pytest.mark.django_db
def test_gateway_error_fails_without_debit(customer, account, old_beneficiary):
    p = pay(customer, account, old_beneficiary, merchant="SIM-ERROR")
    assert p.status == Payment.Status.FAILED
    assert balance(account) == Decimal("250000.00")


@pytest.mark.django_db
def test_insufficient_balance_creates_no_payment(customer, account, old_beneficiary):
    account.balance = Decimal("100.00")
    account.save()
    with pytest.raises(InsufficientFunds):
        pay(customer, account, old_beneficiary, amount="500.00")
    assert Payment.objects.count() == 0


@pytest.mark.django_db
def test_high_risk_payment_is_held_without_debit(customer, account, old_beneficiary):
    p = pay(customer, account, old_beneficiary, amount="150000.00")
    assert p.fraud_decision == "STEP_UP"
    assert p.status == Payment.Status.HELD_FOR_REVIEW
    assert balance(account) == Decimal("250000.00")


@pytest.mark.django_db
def test_new_beneficiary_adds_risk_points(customer, account):
    fresh = Beneficiary.objects.create(
        owner=customer, name="New Payee", destination_ref="T-NEW",
        created_at=NOON - timedelta(hours=2),
    )
    p = pay(customer, account, fresh, amount="500.00")
    assert p.fraud_score == 15
    assert any(r["rule_id"] == "R-05" for r in p.fraud_reasons)


@pytest.mark.django_db
def test_payment_at_night_adds_time_risk(customer, account, old_beneficiary):
    night = timezone.make_aware(datetime(2026, 10, 17, 2, 30))
    p = pay(customer, account, old_beneficiary, now=night)
    assert any(r["rule_id"] == "R-06" for r in p.fraud_reasons)
    assert p.fraud_score == 10


@pytest.mark.django_db
def test_cannot_pay_from_another_customers_account(customer, other_customer, account, old_beneficiary):
    with pytest.raises(PaymentError):
        pay(other_customer, account)
    assert Payment.objects.count() == 0


@pytest.mark.django_db
def test_cannot_use_another_customers_beneficiary(customer, other_customer, account):
    foreign = Beneficiary.objects.create(owner=other_customer, name="X", destination_ref="X")
    with pytest.raises(PaymentError):
        pay(customer, account, foreign)


@pytest.mark.django_db
def test_database_rejects_duplicate_ledger_posting(customer, account, old_beneficiary):
    p = pay(customer, account, old_beneficiary)
    with pytest.raises(IntegrityError), transaction.atomic():
        LedgerEntry.objects.create(account=account, payment=p, amount=Decimal("-500.00"))


@pytest.mark.django_db
def test_database_rejects_negative_balance(account):
    with pytest.raises(IntegrityError), transaction.atomic():
        BankAccount.objects.filter(pk=account.pk).update(balance=Decimal("-1.00"))


@pytest.mark.django_db
def test_terminal_state_cannot_transition(customer, account, old_beneficiary):
    p = pay(customer, account, old_beneficiary)
    with pytest.raises(InvalidTransition):
        transition(p, Payment.Status.SUBMITTED)


@pytest.mark.django_db
def test_successful_payment_writes_audit_events_with_correlation_id(customer, account, old_beneficiary):
    p = pay(customer, account, old_beneficiary)
    events = AuditEvent.objects.filter(correlation_id=p.public_ref)
    actions = set(events.values_list("action", flat=True))
    assert {"FRAUD_EVALUATED", "PAYMENT_SUCCEEDED"} <= actions


@pytest.mark.django_db
def test_audit_rows_cannot_be_updated(customer, account, old_beneficiary):
    pay(customer, account, old_beneficiary)
    event = AuditEvent.objects.first()
    event.action = "TAMPERED"
    with pytest.raises(RuntimeError):
        event.save()


# ----- HTTP layer -----

@pytest.mark.django_db
def test_dashboard_requires_login(client):
    response = client.get(reverse("dashboard"))
    assert response.status_code == 302
    assert "/login/" in response["Location"]


@pytest.mark.django_db
def test_transaction_history_requires_login_and_only_shows_customer_payments(
    client, customer, other_customer, account
):
    pay(customer, account, merchant="SIM-GROCERY")
    other_account = BankAccount.objects.create(
        owner=other_customer, account_ref="T-OTHER", balance=Decimal("1000.00")
    )
    pay(other_customer, other_account, merchant="SIM-ERROR")

    response = client.get(reverse("payments:list"))
    assert response.status_code == 302
    assert "/login/" in response["Location"]

    client.force_login(customer)
    response = client.get(reverse("payments:list"))
    assert response.status_code == 200
    assert b"SIM-GROCERY" in response.content
    assert b"SIM-ERROR" not in response.content


@pytest.mark.django_db
def test_customer_cannot_view_another_customers_payment(client, customer, other_customer, account, old_beneficiary):
    p = pay(customer, account, old_beneficiary)
    client.force_login(other_customer)
    response = client.get(reverse("payments:detail", kwargs={"public_ref": p.public_ref}))
    assert response.status_code == 404


@pytest.mark.django_db
def test_form_only_offers_own_accounts(client, customer, other_customer, account, old_beneficiary):
    BankAccount.objects.create(owner=other_customer, account_ref="T-OTHER", balance=Decimal("1.00"))
    client.force_login(customer)
    response = client.get(reverse("payments:new"))
    choices = [str(c[0]) for c in response.context["form"].fields["source_account"].choices if c[0]]
    assert str(account.pk) in choices
    assert all(BankAccount.objects.get(pk=int(c)).owner == customer for c in choices)


@pytest.mark.django_db
def test_post_payment_end_to_end(client, customer, account, old_beneficiary):
    client.force_login(customer)
    form_page = client.get(reverse("payments:new"))
    key = form_page.context["form"].initial["idempotency_key"]
    response = client.post(reverse("payments:new"), {
        "source_account": account.pk,
        "beneficiary": old_beneficiary.pk,
        "amount": "750.00",
        "merchant_code": "SIM-GROCERY",
        "idempotency_key": key,
    })
    assert response.status_code == 302
    payment = Payment.objects.get()
    assert response["Location"] == reverse("payments:detail", kwargs={"public_ref": payment.public_ref})
    assert balance(account) == Decimal("249250.00")


@pytest.mark.django_db
def test_double_submit_of_same_form_debits_once(client, customer, account, old_beneficiary):
    client.force_login(customer)
    data = {
        "source_account": account.pk, "beneficiary": old_beneficiary.pk,
        "amount": "750.00", "merchant_code": "SIM-GROCERY",
        "idempotency_key": "same-form-key",
    }
    client.post(reverse("payments:new"), data)
    client.post(reverse("payments:new"), data)
    assert Payment.objects.count() == 1
    assert balance(account) == Decimal("249250.00")


@pytest.mark.django_db
def test_detail_page_shows_risk_and_ledger(client, customer, account, old_beneficiary):
    p = pay(customer, account, old_beneficiary)
    client.force_login(customer)
    response = client.get(reverse("payments:detail", kwargs={"public_ref": p.public_ref}))
    assert response.status_code == 200
    assert b"Risk assessment" in response.content
    assert b"-500.00" in response.content
