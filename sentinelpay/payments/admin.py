from django.contrib import admin

from .models import LedgerEntry, Payment

admin.site.register(Payment)
admin.site.register(LedgerEntry)
