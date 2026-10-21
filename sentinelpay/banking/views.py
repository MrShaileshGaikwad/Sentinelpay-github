from datetime import date, datetime, time
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.shortcuts import render
from django.utils import timezone

from payments.models import Payment


@login_required
def dashboard(request):
    # Every queryset is scoped to request.user on the server. Frontend hiding is not a control.
    payments = Payment.objects.filter(customer=request.user)
    today = timezone.localdate()
    month_summary = payments.filter(
        created_at__year=today.year, created_at__month=today.month
    ).aggregate(
        count=Count("pk", filter=Q(status=Payment.Status.SUCCEEDED)),
        spend=Sum("amount", filter=Q(status=Payment.Status.SUCCEEDED)),
    )

    months = []
    for offset in reversed(range(6)):
        month_number = today.month - offset
        year = today.year
        while month_number <= 0:
            month_number += 12
            year -= 1
        month_start = date(year, month_number, 1)
        if month_number == 12:
            next_month = date(year + 1, 1, 1)
        else:
            next_month = date(year, month_number + 1, 1)
        totals = payments.filter(
            created_at__gte=timezone.make_aware(datetime.combine(month_start, time.min)),
            created_at__lt=timezone.make_aware(datetime.combine(next_month, time.min)),
            status=Payment.Status.SUCCEEDED,
        ).aggregate(spend=Sum("amount"))["spend"]
        months.append({"label": month_start.strftime("%b"), "spend": totals or 0})

    max_spend = max((month["spend"] for month in months), default=0)
    for month in months:
        month["height"] = int(month["spend"] / max_spend * 100) if max_spend else 0

    context = {
        "accounts": request.user.accounts.all(),
        "recent_payments": payments.select_related("source_account")[:10],
        "successful_count": payments.filter(status=Payment.Status.SUCCEEDED).count(),
        "monthly_payment_count": month_summary["count"] or 0,
        "monthly_spend": month_summary["spend"] or 0,
        "open_payment_count": payments.filter(
            status__in=[Payment.Status.HELD_FOR_REVIEW, Payment.Status.UNKNOWN, Payment.Status.SUBMITTED]
        ).count(),
        "monthly_activity": months,
    }
    return render(request, "banking/dashboard.html", context)
