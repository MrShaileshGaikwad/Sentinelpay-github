from decimal import Decimal

from django import forms

from banking.models import BankAccount, Beneficiary

from .gateway import SIMULATOR_MERCHANTS


class PaymentForm(forms.Form):
    source_account = forms.ModelChoiceField(queryset=BankAccount.objects.none())
    beneficiary = forms.ModelChoiceField(queryset=Beneficiary.objects.none(), required=False)
    amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    merchant_code = forms.ChoiceField(
        choices=[(code, f"{name} ({code})") for code, (name, _) in SIMULATOR_MERCHANTS.items()]
    )
    idempotency_key = forms.CharField(max_length=64, widget=forms.HiddenInput)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        # Limiting the querysets is the server-side ownership check. A foreign ID fails validation.
        self.fields["source_account"].queryset = user.accounts.all()
        self.fields["beneficiary"].queryset = user.beneficiaries.all()
