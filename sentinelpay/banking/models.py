"""Customer-facing banking data: accounts and beneficiaries. All values are synthetic."""
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class BankAccount(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="accounts"
    )
    account_ref = models.CharField(max_length=20, unique=True)  # synthetic reference
    currency = models.CharField(max_length=3, default="INR")
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(balance__gte=0), name="balance_non_negative"),
        ]

    def __str__(self):
        return f"{self.account_ref} ({self.currency})"

    @property
    def masked_ref(self):
        return f"****{self.account_ref[-4:]}"


class Beneficiary(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="beneficiaries",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=120)
    destination_ref = models.CharField(max_length=20)  # synthetic reference
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.name
