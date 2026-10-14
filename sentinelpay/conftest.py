from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from banking.models import BankAccount, Beneficiary


@pytest.fixture
def customer(db):
    return get_user_model().objects.create_user("alice", password="Test-pass-12345")


@pytest.fixture
def other_customer(db):
    return get_user_model().objects.create_user("bob", password="Test-pass-12345")


@pytest.fixture
def account(customer):
    return BankAccount.objects.create(
        owner=customer, account_ref="T-0001", balance=Decimal("250000.00")
    )


@pytest.fixture
def old_beneficiary(customer):
    # Added 30 days ago, so R-05 (new beneficiary) does not fire.
    return Beneficiary.objects.create(
        owner=customer,
        name="Utility Co",
        destination_ref="T-DEST-1",
        created_at=timezone.now() - timedelta(days=30),
    )
