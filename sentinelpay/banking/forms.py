import re

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Customer


class CustomerProfileForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = (
            "first_name",
            "last_name",
            "email",
            "phone_number",
            "date_of_birth",
            "address",
        )
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            "address": forms.Textarea(attrs={"rows": 3}),
        }

    def clean_phone_number(self):
        value = self.cleaned_data["phone_number"].strip()
        if not value:
            return ""
        if not re.fullmatch(r"\+?[0-9\s-]+", value):
            raise ValidationError("Enter a valid 10-digit Indian mobile number.")
        digits = re.sub(r"\D", "", value)
        if digits.startswith("91") and len(digits) == 12:
            digits = digits[2:]
        if len(digits) != 10 or digits[0] not in "6789":
            raise ValidationError("Enter a valid 10-digit Indian mobile number.")
        return f"+91 {digits}"

    def clean_date_of_birth(self):
        value = self.cleaned_data.get("date_of_birth")
        if value and value > timezone.localdate():
            raise ValidationError("Date of birth cannot be in the future.")
        return value
