"""Customer-facing banking data: accounts and beneficiaries. All values are synthetic."""
from decimal import Decimal
from uuid import uuid4

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


def generate_customer_number():
    return f"SYN{uuid4().hex[:17].upper()}"


class Customer(models.Model):
    class KycStatus(models.TextChoices):
        NOT_PROVIDED = "NOT_PROVIDED", "Details not provided"
        PENDING = "PENDING", "Pending verification"
        IN_REVIEW = "IN_REVIEW", "Under review"
        VERIFIED = "VERIFIED", "Verified"
        REJECTED = "REJECTED", "Verification rejected"

    class RiskLevel(models.TextChoices):
        UNKNOWN = "UNKNOWN", "Not assessed"
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"
        CRITICAL = "CRITICAL", "Critical"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="customer_profile"
    )
    customer_number = models.CharField(
        max_length=20, unique=True, default=generate_customer_number
    )
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    email = models.EmailField(max_length=254, blank=True)
    phone_number = models.CharField(max_length=20, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    address = models.TextField(blank=True)
    kyc_status = models.CharField(
        max_length=20, choices=KycStatus.choices, default=KycStatus.NOT_PROVIDED
    )
    risk_level = models.CharField(
        max_length=20, choices=RiskLevel.choices, default=RiskLevel.UNKNOWN
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "banking_customer"
        ordering = ["customer_number"]

    def __str__(self):
        return self.customer_number

    @property
    def full_name(self):
        return " ".join(part for part in (self.first_name, self.last_name) if part)

    @property
    def profile_complete(self):
        return all(
            (
                self.first_name,
                self.last_name,
                self.email,
                self.phone_number,
                self.date_of_birth,
                self.address,
            )
        )


class BankAccount(models.Model):
    class AccountType(models.TextChoices):
        SAVINGS = "SAVINGS", "Savings"
        CURRENT = "CURRENT", "Current"
        SALARY = "SALARY", "Salary"
        FIXED_DEPOSIT = "FIXED_DEPOSIT", "Fixed deposit"
        UNSPECIFIED = "UNSPECIFIED", "Not specified"

    class AccountStatus(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        FROZEN = "FROZEN", "Frozen"
        CLOSED = "CLOSED", "Closed"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="accounts"
    )
    account_ref = models.CharField(
        max_length=34, unique=True, db_column="account_number"
    )
    account_type = models.CharField(
        max_length=20, choices=AccountType.choices, default=AccountType.UNSPECIFIED
    )
    currency = models.CharField(max_length=3, default="INR")
    balance = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=Decimal("0.00"),
        db_column="available_balance",
    )
    ledger_balance = models.DecimalField(
        max_digits=18, decimal_places=2, default=Decimal("0.00")
    )
    account_status = models.CharField(
        max_length=20, choices=AccountStatus.choices, default=AccountStatus.ACTIVE
    )
    opened_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "banking_account"
        constraints = [
            models.CheckConstraint(condition=Q(balance__gte=0), name="balance_non_negative"),
            models.CheckConstraint(
                condition=Q(ledger_balance__gte=0), name="ledger_balance_non_negative"
            ),
        ]

    def save(self, *args, **kwargs):
        if self._state.adding and self.balance > 0 and self.ledger_balance == 0:
            self.ledger_balance = self.balance
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.account_ref} ({self.currency})"

    @property
    def masked_ref(self):
        return f"****{self.account_ref[-4:]}"


class Beneficiary(models.Model):
    class VerificationStatus(models.TextChoices):
        NOT_VERIFIED = "NOT_VERIFIED", "Not verified"
        PENDING = "PENDING", "Pending"
        VERIFIED = "VERIFIED", "Verified"
        FAILED = "FAILED", "Failed"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="beneficiaries",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=150, db_column="beneficiary_name")
    destination_ref = models.CharField(max_length=34, db_column="beneficiary_account")
    bank_code = models.CharField(max_length=20, blank=True)
    nickname = models.CharField(max_length=50, blank=True)
    verification_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.NOT_VERIFIED,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.name


class Transaction(models.Model):
    class Type(models.TextChoices):
        TRANSFER = "TRANSFER", "Transfer"
        PAYMENT = "PAYMENT", "Payment"

    class Status(models.TextChoices):
        INITIATED = "INITIATED", "Initiated"
        HELD_FOR_REVIEW = "HELD_FOR_REVIEW", "Held for review"
        REJECTED = "REJECTED", "Rejected by fraud policy"
        SUBMITTED = "SUBMITTED", "Submitted"
        SUCCEEDED = "SUCCEEDED", "Succeeded"
        FAILED = "FAILED", "Failed"
        UNKNOWN = "UNKNOWN", "Outcome unknown"

    transaction_reference = models.UUIDField(default=uuid4, unique=True, editable=False)
    payment = models.OneToOneField(
        "payments.Payment", on_delete=models.PROTECT, related_name="banking_transaction"
    )
    account = models.ForeignKey(
        BankAccount, on_delete=models.PROTECT, related_name="transactions"
    )
    beneficiary = models.ForeignKey(
        Beneficiary,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="transactions",
    )
    transaction_type = models.CharField(max_length=30, choices=Type.choices)
    amount = models.DecimalField(max_digits=18, decimal_places=2)
    currency = models.CharField(max_length=3)
    transaction_status = models.CharField(max_length=20, choices=Status.choices)
    channel = models.CharField(max_length=20, default="WEB")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    device_id = models.CharField(max_length=100, blank=True)
    risk_score = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00")
    )
    created_at = models.DateTimeField(default=timezone.now)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "banking_transaction"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0), name="transaction_amount_positive"
            ),
        ]

    def __str__(self):
        return f"{self.transaction_reference} {self.transaction_status}"
