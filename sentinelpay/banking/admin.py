from django.contrib import admin

from .models import BankAccount, Beneficiary

admin.site.register(BankAccount)
admin.site.register(Beneficiary)
