from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from payments.models import Payment


@login_required
def dashboard(request):
    # Every queryset is scoped to request.user on the server. Frontend hiding is not a control.
    context = {
        "accounts": request.user.accounts.all(),
        "recent_payments": Payment.objects.filter(customer=request.user).select_related("source_account")[:10],
    }
    return render(request, "banking/dashboard.html", context)
