from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditEvent
from banking.models import BankAccount, Beneficiary, Customer, Transaction
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
    account.refresh_from_db()
    assert account.ledger_balance == Decimal("249500.00")
    assert LedgerEntry.objects.filter(payment=p).count() == 1
    assert LedgerEntry.objects.get(payment=p).amount == Decimal("-500.00")
    transaction_record = Transaction.objects.get(payment=p)
    assert transaction_record.transaction_status == Transaction.Status.SUCCEEDED
    assert transaction_record.transaction_type == Transaction.Type.TRANSFER
    assert transaction_record.amount == Decimal("500.00")
    assert transaction_record.beneficiary == old_beneficiary


@pytest.mark.django_db
def test_new_account_uses_supplied_available_balance_as_initial_ledger_balance(customer):
    new_account = BankAccount.objects.create(
        owner=customer,
        account_ref="T-OPENING",
        balance=Decimal("1200.00"),
    )

    assert new_account.ledger_balance == Decimal("1200.00")


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
    transaction_record = Transaction.objects.get(payment=p)
    assert transaction_record.transaction_status == Transaction.Status.UNKNOWN
    assert transaction_record.processed_at is None


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
def test_frozen_account_cannot_make_payment(customer, account, old_beneficiary):
    account.account_status = BankAccount.AccountStatus.FROZEN
    account.save(update_fields=["account_status"])

    with pytest.raises(PaymentError, match="active account"):
        pay(customer, account, old_beneficiary)

    assert Payment.objects.count() == 0


@pytest.mark.django_db
def test_high_risk_payment_is_held_without_debit(customer, account, old_beneficiary):
    p = pay(customer, account, old_beneficiary, amount="150000.00")
    assert p.fraud_decision == "STEP_UP"
    assert p.status == Payment.Status.HELD_FOR_REVIEW
    assert balance(account) == Decimal("250000.00")
    assert p.fraud_case.status == "NEW"
    assert p.fraud_case.severity == "MEDIUM"


@pytest.mark.django_db
def test_critical_fraud_decision_is_rejected_without_debit(customer, account, old_beneficiary):
    night = timezone.make_aware(datetime(2026, 10, 17, 2, 0))
    for index in range(5):
        pay(customer, account, old_beneficiary, key=f"history-{index}", now=night)
    balance_after_history = balance(account)
    fresh_beneficiary = Beneficiary.objects.create(
        owner=customer, name="New Payee", destination_ref="T-NEW",
        created_at=night - timedelta(hours=1),
    )

    payment = pay(
        customer, account, fresh_beneficiary, amount="150000.00",
        key="critical-risk", now=night,
    )

    assert payment.fraud_score >= 80
    assert payment.fraud_decision == "DECLINE"
    assert payment.status == Payment.Status.REJECTED
    assert payment.fraud_case.severity == "CRITICAL"
    assert not LedgerEntry.objects.filter(payment=payment).exists()
    assert balance(account) == balance_after_history


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
def test_project_wide_beneficiary_can_be_used_by_any_customer(customer, other_customer, account):
    shared = Beneficiary.objects.create(owner=None, name="Shared Utility", destination_ref="SHARED")
    other_account = BankAccount.objects.create(
        owner=other_customer, account_ref="T-OTHER", balance=Decimal("1000.00"),
        ledger_balance=Decimal("1000.00"),
    )
    payment = pay(other_customer, other_account, shared)
    assert payment.beneficiary == shared


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
    assert {"REQUEST_VALIDATED", "AUTHORIZATION_VERIFIED", "BALANCE_CHECKED", "IDEMPOTENCY_CHECKED"} <= actions


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
def test_login_and_registration_pages_link_to_each_other(client):
    response = client.get(reverse("login"))
    assert response.status_code == 200
    assert b"Create an account" in response.content

    response = client.get(reverse("register"))
    assert response.status_code == 200
    assert b"Log in to your existing account" in response.content


@pytest.mark.django_db
def test_registration_creates_customer_and_signs_user_in(client):
    response = client.post(reverse("register"), {
        "username": "new.customer",
        "first_name": "Mira",
        "last_name": "Shah",
        "email": "mira@example.in",
        "password1": "Secure-Unique-Password-2026!",
        "password2": "Secure-Unique-Password-2026!",
    })

    assert response.status_code == 302
    assert response.url == reverse("dashboard")
    user = get_user_model().objects.get(username="new.customer")
    profile = Customer.objects.get(user=user)
    assert profile.full_name == "Mira Shah"
    assert profile.email == "mira@example.in"
    assert user.check_password("Secure-Unique-Password-2026!")
    assert int(client.session["_auth_user_id"]) == user.pk
    account = BankAccount.objects.get(owner=user)
    assert account.account_type == BankAccount.AccountType.SAVINGS
    assert account.currency == "INR"
    assert account.balance == Decimal("250000.00")
    assert account.ledger_balance == Decimal("250000.00")
    assert account.account_status == BankAccount.AccountStatus.ACTIVE

    payment_page = client.get(reverse("payments:new"))
    source_field = payment_page.context["form"].fields["source_account"]
    assert source_field.queryset.get() == account
    assert b"INR 250,000.00 available" in payment_page.content


@pytest.mark.django_db
def test_registration_rejects_mismatched_passwords(client):
    response = client.post(reverse("register"), {
        "username": "new.customer",
        "first_name": "Mira",
        "last_name": "Shah",
        "email": "mira@example.in",
        "password1": "Secure-Unique-Password-2026!",
        "password2": "Different-Password-2026!",
    })

    assert response.status_code == 200
    assert response.context["form"].errors["password2"]
    assert not get_user_model().objects.filter(username="new.customer").exists()


@pytest.mark.django_db
def test_source_account_choices_include_balance_for_active_owned_accounts(
    client, customer, account
):
    client.force_login(customer)

    response = client.get(reverse("payments:new"))

    source_field = response.context["form"].fields["source_account"]
    assert list(source_field.queryset) == [account]
    assert b"INR 250,000.00 available" in response.content


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
    BankAccount.objects.create(
        owner=other_customer, account_ref="T-OTHER", balance=Decimal("1.00"),
        ledger_balance=Decimal("1.00"),
    )
    client.force_login(customer)
    response = client.get(reverse("payments:new"))
    choices = [str(c[0]) for c in response.context["form"].fields["source_account"].choices if c[0]]
    assert str(account.pk) in choices
    assert all(BankAccount.objects.get(pk=int(c)).owner == customer for c in choices)


@pytest.mark.django_db
def test_payment_form_explains_when_user_has_no_accounts_or_beneficiaries(client, customer):
    client.force_login(customer)

    response = client.get(reverse("payments:new"))

    assert response.status_code == 200
    assert "No active accounts are linked to this user." in response.context["form"].fields[
        "source_account"
    ].help_text
    assert "No active beneficiaries are available." in response.context["form"].fields[
        "beneficiary"
    ].help_text
    assert b'name="beneficiary"' in response.content
    assert b"merchant payment without selecting one" in response.content


@pytest.mark.django_db
def test_payment_form_excludes_inactive_accounts_and_beneficiaries(
    client, customer, account, old_beneficiary
):
    frozen = BankAccount.objects.create(
        owner=customer,
        account_ref="T-FROZEN",
        balance=Decimal("1000.00"),
        ledger_balance=Decimal("1000.00"),
        account_status=BankAccount.AccountStatus.FROZEN,
    )
    inactive = Beneficiary.objects.create(
        owner=customer,
        name="Inactive Payee",
        destination_ref="T-INACTIVE",
        is_active=False,
    )
    client.force_login(customer)

    response = client.get(reverse("payments:new"))

    account_choices = {
        str(value) for value, _ in response.context["form"].fields["source_account"].choices
        if value
    }
    beneficiary_choices = {
        str(value) for value, _ in response.context["form"].fields["beneficiary"].choices
        if value
    }
    assert str(account.pk) in account_choices
    assert str(frozen.pk) not in account_choices
    assert str(old_beneficiary.pk) in beneficiary_choices
    assert str(inactive.pk) not in beneficiary_choices


@pytest.mark.django_db
def test_customer_profile_is_editable_and_does_not_allow_customer_to_set_kyc(client, customer):
    client.force_login(customer)

    response = client.get(reverse("customer-profile"))

    assert response.status_code == 200
    assert b"not assessed" in response.content
    profile = Customer.objects.get(user=customer)
    assert profile.customer_number.startswith("SYN")
    assert profile.kyc_status == Customer.KycStatus.NOT_PROVIDED

    response = client.post(reverse("customer-profile"), {
        "first_name": "Ananya",
        "last_name": "Rao",
        "email": "ananya@example.in",
        "phone_number": "9876543210",
        "date_of_birth": "1995-04-12",
        "address": "Pune, Maharashtra",
        "kyc_status": Customer.KycStatus.VERIFIED,
        "risk_level": Customer.RiskLevel.LOW,
    })

    assert response.status_code == 302
    profile.refresh_from_db()
    customer.refresh_from_db()
    assert profile.full_name == "Ananya Rao"
    assert profile.phone_number == "+91 9876543210"
    assert profile.profile_complete
    assert profile.kyc_status == Customer.KycStatus.NOT_PROVIDED
    assert profile.risk_level == Customer.RiskLevel.UNKNOWN
    assert customer.first_name == "Ananya"
    assert customer.email == "ananya@example.in"


@pytest.mark.django_db
def test_header_uses_customer_profile_name(client, customer):
    Customer.objects.create(user=customer, first_name="Sharvari", last_name="Kshirsagar")
    client.force_login(customer)

    response = client.get(reverse("dashboard"))

    assert b'<span class="avatar">S</span>' in response.content
    assert b'<span class="nav-username">Sharvari Kshirsagar</span>' in response.content
    assert b"alice</span>" not in response.content


@pytest.mark.django_db
def test_sign_out_returns_to_login_page(client, customer):
    client.force_login(customer)

    response = client.post(reverse("logout"))

    assert response.status_code == 302
    assert response.url == reverse("login")
    response = client.get(response.url)
    assert response.status_code == 200
    assert b"Welcome back" in response.content
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_customer_profile_rejects_invalid_indian_mobile(client, customer):
    client.force_login(customer)

    response = client.post(reverse("customer-profile"), {
        "first_name": "Ananya",
        "last_name": "Rao",
        "email": "ananya@example.in",
        "phone_number": "12345",
        "date_of_birth": "1995-04-12",
        "address": "Pune, Maharashtra",
    })

    assert response.status_code == 200
    assert b"valid 10-digit Indian mobile number" in response.content
    assert Customer.objects.get(user=customer).phone_number == ""


@pytest.mark.django_db
def test_form_offers_project_wide_and_own_beneficiaries(client, customer, other_customer, old_beneficiary):
    shared = Beneficiary.objects.create(owner=None, name="Shared Utility", destination_ref="SHARED")
    foreign = Beneficiary.objects.create(owner=other_customer, name="Private Utility", destination_ref="PRIVATE")
    client.force_login(customer)
    response = client.get(reverse("payments:new"))
    field = response.context["form"].fields["beneficiary"]
    choices = [str(value) for value, _ in field.choices if value]
    labels = {str(value): label for value, label in field.choices}
    assert str(old_beneficiary.pk) in choices
    assert str(shared.pk) in choices
    assert str(foreign.pk) not in choices
    assert labels[str(shared.pk)] == "Shared Utility (Project-wide)"
    assert b"Project-wide beneficiaries are shared across customers" in response.content


@pytest.mark.django_db
def test_authenticated_layout_uses_responsive_workspace_navigation(client, customer):
    client.force_login(customer)

    response = client.get(reverse("dashboard"))

    assert response.status_code == 200
    assert b'class="workspace-nav" aria-label="Main navigation"' in response.content
    assert b'href="/payments/new/"' in response.content
    assert b'href="/payments/fraud/"' not in response.content
    assert b"Balances across your linked accounts" in response.content
    assert b"Balances from your demo accounts" not in response.content


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
    assert response["Location"] == reverse("payments:review")
    assert Payment.objects.count() == 0
    assert balance(account) == Decimal("250000.00")

    review = client.get(reverse("payments:review"))
    assert review.status_code == 200
    assert b"Review your payment" in review.content
    assert b"Transaction reference" in review.content
    assert b"Assigned after submission" in review.content
    assert "••••ST-1".encode() in review.content
    assert b"Payment route" in review.content
    assert b"Utility Co" in review.content
    response = client.post(reverse("payments:review"), {"confirm": "yes"})
    assert response.status_code == 302
    payment = Payment.objects.get()
    assert response["Location"] == reverse("payments:detail", kwargs={"public_ref": payment.public_ref})
    assert balance(account) == Decimal("249250.00")


@pytest.mark.django_db
def test_payment_review_can_be_cancelled_without_creating_a_payment(client, customer, account, old_beneficiary):
    client.force_login(customer)
    client.post(reverse("payments:new"), {
        "source_account": account.pk,
        "beneficiary": old_beneficiary.pk,
        "amount": "750.00",
        "merchant_code": "SIM-GROCERY",
        "idempotency_key": "cancel-this-payment",
    })

    response = client.post(reverse("payments:review"), {"cancel": "yes"})

    assert response.status_code == 302
    assert Payment.objects.count() == 0
    assert balance(account) == Decimal("250000.00")
    assert "payment_review" not in client.session


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
    client.post(reverse("payments:review"), {"confirm": "yes"})
    client.post(reverse("payments:review"), {"confirm": "yes"})
    assert Payment.objects.count() == 1
    assert balance(account) == Decimal("249250.00")


@pytest.mark.django_db
def test_detail_page_shows_risk_and_ledger(client, customer, account, old_beneficiary):
    p = pay(customer, account, old_beneficiary)
    client.force_login(customer)
    response = client.get(reverse("payments:detail", kwargs={"public_ref": p.public_ref}))
    assert response.status_code == 200
    assert b"Risk assessment" in response.content
    assert b'aria-valuenow="0"' in response.content
    assert b"Processing timeline" in response.content
    assert b"-500.00" in response.content


@pytest.mark.django_db
def test_statement_csv_is_customer_scoped_and_uses_ledger_debits(client, customer, other_customer, account, old_beneficiary):
    pay(customer, account, old_beneficiary)
    other_account = BankAccount.objects.create(
        owner=other_customer, account_ref="T-OTHER", balance=Decimal("1000.00"),
        ledger_balance=Decimal("1000.00"),
    )
    pay(other_customer, other_account, merchant="SIM-ERROR")

    client.force_login(customer)
    response = client.get(reverse("payments:statement-csv"))

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    assert b"500.00" in response.content
    assert b"-500.00" not in response.content
    assert b"T-OTHER" not in response.content
    assert b"SIM-GROCERY" in response.content


@pytest.mark.django_db
def test_dashboard_uses_customer_payment_data_and_masks_account_reference(
    client, customer, other_customer, account, old_beneficiary
):
    pay(customer, account, old_beneficiary, now=timezone.now())
    other_account = BankAccount.objects.create(
        owner=other_customer, account_ref="T-OTHER", balance=Decimal("1000.00"),
        ledger_balance=Decimal("1000.00"),
    )
    pay(other_customer, other_account, merchant="SIM-GROCERY", key="other-payment", now=timezone.now())
    client.force_login(customer)

    response = client.get(reverse("dashboard"))

    assert response.status_code == 200
    assert response.context["successful_count"] == 1
    assert response.context["monthly_spend"] == Decimal("500.00")
    assert len(response.context["monthly_activity"]) == 6
    assert b"****0001" in response.content
    assert b"T-OTHER" not in response.content


@pytest.mark.django_db
def test_fraud_console_requires_analyst_role_and_audits_case_updates(
    client, customer, account, old_beneficiary
):
    payment = pay(customer, account, old_beneficiary, amount="150000.00")
    case = payment.fraud_case
    client.force_login(customer)
    assert client.get(reverse("payments:fraud-center")).status_code == 403
    assert client.get(reverse("payments:fraud-case", kwargs={"case_id": case.pk})).status_code == 403

    analyst_group, _ = Group.objects.get_or_create(name="Fraud Analysts")
    customer.groups.add(analyst_group)
    response = client.get(reverse("payments:fraud-center"))
    assert response.status_code == 200
    assert b"Fraud intelligence" in response.content

    response = client.post(
        reverse("payments:fraud-case", kwargs={"case_id": case.pk}),
        {"status": "INVESTIGATING", "analyst_note": "Reviewing the triggered amount rule."},
    )
    assert response.status_code == 302
    case.refresh_from_db()
    assert case.status == "INVESTIGATING"
    assert case.assigned_reviewer == customer
    event = AuditEvent.objects.get(
        object_type="FraudCase", object_id=str(case.pk), action="FRAUD_CASE_UPDATED"
    )
    assert event.metadata["from_status"] == "NEW"
    assert event.metadata["to_status"] == "INVESTIGATING"
    assert event.metadata["note"] == "Reviewing the triggered amount rule."


@pytest.mark.django_db
def test_customer_transaction_filters_are_applied_server_side(client, customer, account, old_beneficiary):
    pay(customer, account, old_beneficiary, amount="500.00", key="small")
    pay(customer, account, old_beneficiary, amount="750.00", key="large")
    client.force_login(customer)

    response = client.get(reverse("payments:list"), {"amount_min": "700.00", "status": "SUCCEEDED"})

    assert response.status_code == 200
    assert response.context["page_obj"].paginator.count == 1
    assert response.context["page_obj"][0].amount == Decimal("750.00")
