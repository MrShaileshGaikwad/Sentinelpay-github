import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from banking.models import BankAccount, Beneficiary


class Payment(models.Model):
    class Status(models.TextChoices):
        INITIATED = "INITIATED", "Initiated"
        HELD_FOR_REVIEW = "HELD_FOR_REVIEW", "Held for review"
        REJECTED = "REJECTED", "Rejected by fraud policy"
        SUBMITTED = "SUBMITTED", "Submitted to gateway"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"
        UNKNOWN = "UNKNOWN", "Outcome unknown"

    public_ref = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payments")
    source_account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, related_name="payments")
    beneficiary = models.ForeignKey(Beneficiary, on_delete=models.PROTECT, null=True, blank=True, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3)
    merchant_code = models.CharField(max_length=20)
    idempotency_key = models.CharField(max_length=64)
    request_fingerprint = models.CharField(max_length=64)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.INITIATED)
    fraud_score = models.PositiveSmallIntegerField(null=True, blank=True)
    fraud_decision = models.CharField(max_length=20, blank=True)
    fraud_ruleset_version = models.CharField(max_length=20, blank=True)
    fraud_reasons = models.JSONField(default=list, blank=True)
    gateway_code = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["customer", "idempotency_key"], name="uniq_idempotency_key_per_customer"),
            models.CheckConstraint(condition=Q(amount__gt=0), name="payment_amount_positive"),
        ]

    def __str__(self):
        return f"Payment {self.public_ref} {self.status}"


class LedgerEntry(models.Model):
    """Debit posted to an account for a payment. Negative amount means money left the account."""

    account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, related_name="ledger_entries")
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="ledger_entries")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            # One posting per payment and account: a duplicate post is rejected by the database.
            models.UniqueConstraint(fields=["payment", "account"], name="one_ledger_entry_per_payment_account"),
            models.CheckConstraint(condition=~Q(amount=0), name="ledger_entry_not_zero"),
        ]
