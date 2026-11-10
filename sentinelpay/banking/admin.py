from django.contrib import admin

from .models import BankAccount, Beneficiary, Customer, Transaction

admin.site.register(BankAccount)
admin.site.register(Beneficiary)
admin.site.register(Customer)


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = (
        "transaction_reference",
        "transaction_type",
        "amount",
        "currency",
        "transaction_status",
        "created_at",
    )
    list_filter = ("transaction_type", "transaction_status", "channel")
    readonly_fields = tuple(field.name for field in Transaction._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
