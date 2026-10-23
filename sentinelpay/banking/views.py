from datetime import date, datetime, time
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import transaction as db_transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import redirect, render
from django.utils import timezone

from .forms import CustomerProfileForm, CustomerRegistrationForm
from .models import BankAccount, Customer, generate_account_ref
from payments.models import Payment


DEMO_ACCOUNT_STARTING_BALANCE = Decimal("250000.00")


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    form = CustomerRegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with db_transaction.atomic():
            user = form.save()
            Customer.objects.create(
                user=user,
                first_name=user.first_name,
                last_name=user.last_name,
                email=user.email,
            )
            BankAccount.objects.create(
                owner=user,
                account_ref=generate_account_ref(),
                account_type=BankAccount.AccountType.SAVINGS,
                currency="INR",
                balance=DEMO_ACCOUNT_STARTING_BALANCE,
                account_status=BankAccount.AccountStatus.ACTIVE,
                opened_at=timezone.now(),
            )
        login(request, user)
        messages.success(request, "Your SentinelPay account has been created.")
        return redirect("dashboard")

    return render(request, "registration/register.html", {"form": form})


def _customer_profile(user):
    profile, _ = Customer.objects.get_or_create(
        user=user,
        defaults={
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
        },
    )
    return profile


@login_required
def dashboard(request):
    # Every queryset is scoped to request.user on the server. Frontend hiding is not a control.
    profile = _customer_profile(request.user)
    payments = Payment.objects.filter(customer=request.user)
    today = timezone.localdate()
    current_month_start = date(today.year, today.month, 1)
    if today.month == 12:
        next_month_start = date(today.year + 1, 1, 1)
    else:
        next_month_start = date(today.year, today.month + 1, 1)
    month_summary = payments.filter(
        created_at__gte=timezone.make_aware(
            datetime.combine(current_month_start, time.min)
        ),
        created_at__lt=timezone.make_aware(
            datetime.combine(next_month_start, time.min)
        ),
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
        "customer_profile": profile,
        "accounts": request.user.accounts.all(),
        "recent_payments": payments.select_related(
            "source_account", "banking_transaction"
        )[:10],
        "successful_count": payments.filter(status=Payment.Status.SUCCEEDED).count(),
        "monthly_payment_count": month_summary["count"] or 0,
        "monthly_spend": month_summary["spend"] or 0,
        "open_payment_count": payments.filter(
            status__in=[Payment.Status.HELD_FOR_REVIEW, Payment.Status.UNKNOWN, Payment.Status.SUBMITTED]
        ).count(),
        "monthly_activity": months,
    }
    return render(request, "banking/dashboard.html", context)


@login_required
def customer_profile(request):
    profile = _customer_profile(request.user)
    form = CustomerProfileForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        with db_transaction.atomic():
            profile = form.save()
            user = request.user
            user.first_name = profile.first_name
            user.last_name = profile.last_name
            user.email = profile.email
            user.save(update_fields=["first_name", "last_name", "email"])
        messages.success(request, "Your customer profile has been updated.")
        return redirect("dashboard")
    return render(
        request,
        "banking/customer_profile.html",
        {"form": form, "customer_profile": profile},
    )
