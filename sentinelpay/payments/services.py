"""
Payment orchestration. Views call create_payment and contain no business logic.

Idempotency: (customer, idempotency_key) is unique in the database. A repeat
with the same fingerprint returns the original payment. A repeat with a
different fingerprint raises IdempotencyConflict.

Money: a debit is posted only when the simulator reports SUCCESS. TIMEOUT
leaves the payment UNKNOWN with no debit, and the system never retries it
automatically.
"""
import hashlib
import json
from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Avg, F, Q
from django.utils import timezone

from audit.services import record_event
from banking.models import BankAccount, Beneficiary, Transaction
from fraud_engine.engine import PaymentContext, evaluate

from .gateway import SIMULATOR_MERCHANTS, GatewayOutcome, SimulatedGateway
from .models import FraudCase, LedgerEntry, Payment
from .states import Status, transition

HOME_COUNTRY = "IN"


class PaymentError(Exception):
    pass


class InsufficientFunds(PaymentError):
    pass


class IdempotencyConflict(PaymentError):
    pass


def _fingerprint(customer_id, account_id, beneficiary_id, amount, merchant_code):
    canonical = json.dumps(
        {
            "customer": customer_id,
            "account": account_id,
            "beneficiary": beneficiary_id,
            "amount": f"{amount:.2f}",
            "merchant": merchant_code,
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _replay_or_conflict(customer, idempotency_key, fingerprint):
    existing = Payment.objects.filter(customer=customer, idempotency_key=idempotency_key).first()
    if existing is None:
        return None
    if existing.request_fingerprint != fingerprint:
        raise IdempotencyConflict("This idempotency key was already used for a different payment.")
    return existing


def _build_context(customer, account, beneficiary, amount, now) -> PaymentContext:
    window_start = now - timedelta(days=30)
    avg = (
        Payment.objects.filter(source_account=account, status=Status.SUCCEEDED, created_at__gte=window_start)
        .aggregate(avg=Avg("amount"))["avg"]
    )
    recent = Payment.objects.filter(customer=customer, created_at__gte=now - timedelta(hours=1))
    local_time = timezone.localtime(now)
    return PaymentContext(
        amount=amount,
        customer_avg_amount_30d=Decimal(str(avg or "0")),
        payments_last_hour=recent.count(),
        failed_attempts_last_hour=recent.filter(status__in=[Status.FAILED, Status.REJECTED]).count(),
        beneficiary_added_at=beneficiary.created_at if beneficiary else None,
        payment_time=local_time,
        # LIMITATION: this slice captures no device or IP data, so R-07 and R-08 never fire.
        is_new_device=False,
        ip_country=HOME_COUNTRY,
        home_country=HOME_COUNTRY,
    )


def _post_debit(payment: Payment) -> bool:
    updated = BankAccount.objects.filter(
        pk=payment.source_account_id,
        balance__gte=payment.amount,
        ledger_balance__gte=payment.amount,
    ).update(
        balance=F("balance") - payment.amount,
        ledger_balance=F("ledger_balance") - payment.amount,
    )
    if updated != 1:
        return False
    LedgerEntry.objects.create(account_id=payment.source_account_id, payment=payment, amount=-payment.amount)
    return True


def _record_stage(payment, customer, action, label):
    record_event(
        actor=customer,
        action=action,
        object_type="Payment",
        object_id=payment.pk,
        correlation_id=payment.public_ref,
        metadata={"stage": label},
    )


def _process(*, customer, account_id, beneficiary_id, amount, merchant_code, idempotency_key, fingerprint, now):
    account = BankAccount.objects.select_for_update().filter(
        pk=account_id, owner=customer
    ).first()
    if account is None:
        raise PaymentError("Source account was not found.")
    if account.account_status != BankAccount.AccountStatus.ACTIVE:
        raise PaymentError("Payments can only be made from an active account.")
    beneficiary = None
    if beneficiary_id is not None:
        beneficiary = Beneficiary.objects.filter(pk=beneficiary_id).filter(
            Q(owner=customer) | Q(owner__isnull=True)
        ).filter(is_active=True).first()
        if beneficiary is None:
            raise PaymentError("Beneficiary was not found.")
    if amount > account.balance:
        raise InsufficientFunds("Insufficient balance for this payment.")

    evaluation = evaluate(_build_context(customer, account, beneficiary, amount, now))

    payment = Payment.objects.create(
        customer=customer,
        source_account=account,
        beneficiary=beneficiary,
        amount=amount,
        currency=account.currency,
        merchant_code=merchant_code,
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
        fraud_score=evaluation.score,
        fraud_decision=evaluation.decision,
        fraud_ruleset_version=evaluation.ruleset_version,
        fraud_reasons=[
            {"rule_id": r.rule_id, "points": r.points, "explanation": r.explanation}
            for r in evaluation.triggered_rules
        ],
        created_at=now,
    )
    _record_stage(payment, customer, "REQUEST_VALIDATED", "Request validated")
    _record_stage(payment, customer, "AUTHORIZATION_VERIFIED", "Account and beneficiary ownership verified")
    _record_stage(payment, customer, "BALANCE_CHECKED", "Available balance checked")
    _record_stage(payment, customer, "IDEMPOTENCY_CHECKED", "Idempotency key accepted")
    _record_stage(payment, customer, "PAYMENT_INITIATED", "Payment initiated")
    record_event(
        actor=customer, action="FRAUD_EVALUATED", object_type="Payment", object_id=payment.pk,
        correlation_id=payment.public_ref,
        metadata={"score": evaluation.score, "decision": evaluation.decision,
                  "ruleset": evaluation.ruleset_version},
    )

    if evaluation.decision == "DECLINE":
        transition(payment, Status.REJECTED)
    elif evaluation.decision in ("REVIEW", "STEP_UP"):
        # The step-up challenge flow is not built in this slice, so the payment is held without a debit.
        transition(payment, Status.HELD_FOR_REVIEW)
    else:
        transition(payment, Status.SUBMITTED)
        _record_stage(payment, customer, "PAYMENT_SUBMITTED", "Submitted to payment simulator")
        response = SimulatedGateway().submit(merchant_code, amount, reference=str(payment.public_ref))
        payment.gateway_code = response.code
        payment.save(update_fields=["gateway_code", "updated_at"])
        if response.outcome is GatewayOutcome.SUCCESS:
            if _post_debit(payment):
                transition(payment, Status.SUCCEEDED)
            else:
                # Simulator said success but the balance check failed at posting. Flagged for reconciliation.
                payment.gateway_code = "SIM_POST_REJECTED"
                payment.save(update_fields=["gateway_code", "updated_at"])
                transition(payment, Status.FAILED)
        elif response.outcome is GatewayOutcome.TIMEOUT:
            transition(payment, Status.UNKNOWN)
        else:
            transition(payment, Status.FAILED)

    if payment.status in (Status.HELD_FOR_REVIEW, Status.REJECTED):
        severity = (
            FraudCase.Severity.CRITICAL if evaluation.score >= 80
            else FraudCase.Severity.HIGH if evaluation.score >= 50
            else FraudCase.Severity.MEDIUM
        )
        case = FraudCase.objects.create(payment=payment, severity=severity)
        record_event(
            actor=None,
            action="FRAUD_CASE_CREATED",
            object_type="FraudCase",
            object_id=case.pk,
            correlation_id=payment.public_ref,
            metadata={"severity": severity, "payment_ref": str(payment.public_ref)},
        )

    transaction_record = Transaction.objects.create(
        payment=payment,
        account=account,
        beneficiary=beneficiary,
        transaction_type=(
            Transaction.Type.TRANSFER if beneficiary else Transaction.Type.PAYMENT
        ),
        amount=payment.amount,
        currency=payment.currency,
        transaction_status=payment.status,
        risk_score=evaluation.score,
        created_at=payment.created_at,
        processed_at=(
            payment.updated_at
            if payment.status not in (Status.SUBMITTED, Status.UNKNOWN)
            else None
        ),
    )
    record_event(
        actor=customer, action=f"PAYMENT_{payment.status}", object_type="Payment", object_id=payment.pk,
        correlation_id=payment.public_ref,
        metadata={
            "gateway_code": payment.gateway_code,
            "stage": f"Payment {payment.get_status_display().lower()}",
            "transaction_reference": str(transaction_record.transaction_reference),
        },
    )
    return payment


def create_payment(*, customer, account_id, beneficiary_id, amount, merchant_code, idempotency_key, now=None) -> Payment:
    """now is injectable so that time-based rules are deterministic in tests and demos."""
    now = now or timezone.now()
    if amount <= 0:
        raise PaymentError("Amount must be positive.")
    if merchant_code not in SIMULATOR_MERCHANTS:
        raise PaymentError("Unknown merchant.")

    fingerprint = _fingerprint(customer.pk, account_id, beneficiary_id, amount, merchant_code)
    existing = _replay_or_conflict(customer, idempotency_key, fingerprint)
    if existing is not None:
        return existing

    try:
        with transaction.atomic():
            return _process(
                customer=customer, account_id=account_id, beneficiary_id=beneficiary_id,
                amount=amount, merchant_code=merchant_code,
                idempotency_key=idempotency_key, fingerprint=fingerprint, now=now,
            )
    except IntegrityError:
        # A concurrent request with the same key won the race. Return its result or report a conflict.
        existing = _replay_or_conflict(customer, idempotency_key, fingerprint)
        if existing is not None:
            return existing
        raise
