from decimal import Decimal

from django import forms
from django.db.models import Q

from banking.models import BankAccount, Beneficiary

from .gateway import SIMULATOR_MERCHANTS
from .models import FraudCase, Payment


class BeneficiaryChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        label = str(obj)
        return f"{label} (Project-wide)" if obj.owner_id is None else label


class PaymentForm(forms.Form):
    source_account = forms.ModelChoiceField(queryset=BankAccount.objects.none())
    beneficiary = BeneficiaryChoiceField(
        queryset=Beneficiary.objects.none(),
        required=False,
        help_text="Project-wide beneficiaries are shared across customers; your personal beneficiaries are only visible to you.",
    )
    amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    merchant_code = forms.ChoiceField(
        choices=[(code, f"{name} ({code})") for code, (name, _) in SIMULATOR_MERCHANTS.items()]
    )
    idempotency_key = forms.CharField(max_length=64, widget=forms.HiddenInput)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        # Limiting the querysets is the server-side ownership check. A foreign ID fails validation.
        self.fields["source_account"].queryset = user.accounts.all()
        self.fields["beneficiary"].queryset = Beneficiary.objects.filter(
            Q(owner=user) | Q(owner__isnull=True)
        ).order_by("name")


class PaymentFilterForm(forms.Form):
    search = forms.CharField(required=False, max_length=64, label="Reference or merchant")
    status = forms.ChoiceField(
        required=False, choices=[("", "All statuses"), *Payment.Status.choices]
    )
    risk = forms.ChoiceField(
        required=False,
        choices=[
            ("", "All risk levels"),
            ("LOW", "Low"),
            ("MEDIUM", "Medium"),
            ("HIGH", "High"),
            ("CRITICAL", "Critical"),
        ],
    )
    date_from = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    amount_min = forms.DecimalField(required=False, min_value=Decimal("0.01"), decimal_places=2)
    amount_max = forms.DecimalField(required=False, min_value=Decimal("0.01"), decimal_places=2)

    def clean(self):
        cleaned_data = super().clean()
        date_from = cleaned_data.get("date_from")
        date_to = cleaned_data.get("date_to")
        amount_min = cleaned_data.get("amount_min")
        amount_max = cleaned_data.get("amount_max")
        if date_from and date_to and date_from > date_to:
            self.add_error("date_to", "The end date must be on or after the start date.")
        if amount_min is not None and amount_max is not None and amount_min > amount_max:
            self.add_error("amount_max", "The maximum must be at least the minimum.")
        return cleaned_data

    def apply_to(self, queryset):
        if not self.is_valid():
            return queryset
        data = self.cleaned_data
        if data.get("search"):
            queryset = queryset.filter(
                Q(public_ref__icontains=data["search"]) | Q(merchant_code__icontains=data["search"])
            )
        if data.get("status"):
            queryset = queryset.filter(status=data["status"])
        if data.get("date_from"):
            queryset = queryset.filter(created_at__date__gte=data["date_from"])
        if data.get("date_to"):
            queryset = queryset.filter(created_at__date__lte=data["date_to"])
        if data.get("amount_min") is not None:
            queryset = queryset.filter(amount__gte=data["amount_min"])
        if data.get("amount_max") is not None:
            queryset = queryset.filter(amount__lte=data["amount_max"])
        risk = data.get("risk")
        if risk == "LOW":
            queryset = queryset.filter(fraud_score__lt=30)
        elif risk == "MEDIUM":
            queryset = queryset.filter(fraud_score__gte=30, fraud_score__lt=50)
        elif risk == "HIGH":
            queryset = queryset.filter(fraud_score__gte=50, fraud_score__lt=80)
        elif risk == "CRITICAL":
            queryset = queryset.filter(fraud_score__gte=80)
        return queryset


class FraudCaseUpdateForm(forms.Form):
    status = forms.ChoiceField(choices=FraudCase.Status.choices)
    analyst_note = forms.CharField(
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Record the reason for this case update."}),
    )


class FraudMonitorFilterForm(PaymentFilterForm):
    case_status = forms.ChoiceField(
        required=False,
        choices=[("", "All case statuses"), *FraudCase.Status.choices],
        label="Case status",
    )
