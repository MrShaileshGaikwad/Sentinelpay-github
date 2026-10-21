import csv
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from audit.models import AuditEvent
from banking.permissions import user_can_review_fraud

from .forms import (
    FraudCaseUpdateForm,
    FraudMonitorFilterForm,
    PaymentFilterForm,
    PaymentForm,
)
from .models import FraudCase, Payment
from .services import IdempotencyConflict, InsufficientFunds, PaymentError, create_payment

CASE_TRANSITIONS = {
    FraudCase.Status.NEW: {
        FraudCase.Status.INVESTIGATING, FraudCase.Status.ESCALATED,
        FraudCase.Status.RESOLVED, FraudCase.Status.FALSE_POSITIVE,
    },
    FraudCase.Status.INVESTIGATING: {
        FraudCase.Status.NEW, FraudCase.Status.ESCALATED,
        FraudCase.Status.RESOLVED, FraudCase.Status.FALSE_POSITIVE,
    },
    FraudCase.Status.ESCALATED: {
        FraudCase.Status.INVESTIGATING, FraudCase.Status.RESOLVED,
        FraudCase.Status.FALSE_POSITIVE,
    },
    FraudCase.Status.RESOLVED: set(),
    FraudCase.Status.FALSE_POSITIVE: set(),
}


def _require_fraud_access(user):
    if not user_can_review_fraud(user):
        raise PermissionDenied


def _payment_queryset():
    return Payment.objects.select_related(
        "customer", "source_account", "beneficiary"
    ).annotate(posted_debit=Sum("ledger_entries__amount"))


def _filtered_payments(request, queryset, form_class=PaymentFilterForm):
    form = form_class(request.GET)
    if form.is_valid():
        queryset = form.apply_to(queryset)
    return form, queryset


def _payment_timeline(payment):
    events = list(AuditEvent.objects.filter(
        object_type="Payment", object_id=str(payment.pk)
    ).order_by("created_at", "pk"))
    elapsed_ms = (
        max(0, int((events[-1].created_at - events[0].created_at).total_seconds() * 1000))
        if len(events) > 1 else 0
    )
    return events, elapsed_ms


@login_required
def payment_create(request):
    if request.method == "POST":
        form = PaymentForm(request.POST, user=request.user)
        if form.is_valid():
            data = form.cleaned_data
            request.session["payment_review"] = {
                "source_account": str(data["source_account"].pk),
                "beneficiary": str(data["beneficiary"].pk) if data["beneficiary"] else "",
                "amount": str(data["amount"]),
                "merchant_code": data["merchant_code"],
                "idempotency_key": data["idempotency_key"],
            }
            return redirect("payments:review")
    else:
        form = PaymentForm(user=request.user, initial={"idempotency_key": str(uuid.uuid4())})
    return render(request, "payments/payment_form.html", {"form": form})


@login_required
def payment_review(request):
    draft = request.session.get("payment_review")
    if not draft:
        messages.info(request, "Start a payment to review its details.")
        return redirect("payments:new")
    if request.method == "POST" and request.POST.get("cancel") == "yes":
        request.session.pop("payment_review", None)
        messages.info(request, "Payment cancelled before submission.")
        return redirect("dashboard")

    form = PaymentForm(draft, user=request.user)
    if not form.is_valid():
        request.session.pop("payment_review", None)
        messages.error(request, "The saved payment details are no longer valid. Please start again.")
        return redirect("payments:new")

    if request.method == "POST":
        if request.POST.get("confirm") != "yes":
            return HttpResponse("Confirm the payment using the review button.", status=400)
        data = form.cleaned_data
        try:
            payment = create_payment(
                customer=request.user,
                account_id=data["source_account"].pk,
                beneficiary_id=data["beneficiary"].pk if data["beneficiary"] else None,
                amount=data["amount"],
                merchant_code=data["merchant_code"],
                idempotency_key=data["idempotency_key"],
            )
        except InsufficientFunds as exc:
            form.add_error("amount", str(exc))
        except IdempotencyConflict as exc:
            form.add_error(None, str(exc) + " Start a new payment from the form.")
        except PaymentError as exc:
            form.add_error(None, str(exc))
        else:
            request.session.pop("payment_review", None)
            return redirect("payments:detail", public_ref=payment.public_ref)

    return render(request, "payments/payment_review.html", {
        "form": form,
        "source_account": form.cleaned_data["source_account"],
        "beneficiary": form.cleaned_data["beneficiary"],
        "amount": form.cleaned_data["amount"],
        "merchant_code": form.cleaned_data["merchant_code"],
    })


@login_required
def payment_detail(request, public_ref):
    payment = get_object_or_404(
        Payment.objects.select_related("source_account", "beneficiary"),
        public_ref=public_ref,
        customer=request.user,
    )
    timeline, timeline_duration_ms = _payment_timeline(payment)
    return render(request, "payments/payment_detail.html", {
        "payment": payment,
        "ledger_entries": payment.ledger_entries.select_related("account").all(),
        "fraud_case": FraudCase.objects.filter(payment=payment).first(),
        "timeline": timeline,
        "timeline_duration_ms": timeline_duration_ms,
    })


@login_required
def payment_list(request):
    payments = Payment.objects.filter(customer=request.user).select_related("source_account")
    filter_form, payments = _filtered_payments(request, payments)
    page_obj = Paginator(payments, 20).get_page(request.GET.get("page"))
    filters = request.GET.copy()
    filters.pop("page", None)
    return render(request, "payments/transaction_list.html", {
        "page_obj": page_obj,
        "filter_form": filter_form,
        "filter_query": filters.urlencode(),
    })


@login_required
def statement_csv(request):
    payments = _payment_queryset().filter(customer=request.user)
    filter_form, payments = _filtered_payments(request, payments)
    if not filter_form.is_valid():
        return HttpResponse("Invalid statement filters. Review the transaction history form.", status=400)

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="sentinelpay-statement.csv"'
    writer = csv.writer(response)
    writer.writerow([
        "Date and time", "Transaction reference", "Account", "Merchant",
        "Currency", "Requested amount", "Amount debited", "Status",
        "Fraud decision", "Risk score",
    ])
    for payment in payments.order_by("created_at", "pk"):
        writer.writerow([
            timezone.localtime(payment.created_at).isoformat(),
            str(payment.public_ref),
            payment.source_account.masked_ref,
            payment.merchant_code,
            payment.currency,
            str(payment.amount),
            str(-payment.posted_debit) if payment.posted_debit is not None else "0.00",
            payment.get_status_display(),
            payment.fraud_decision,
            payment.fraud_score if payment.fraud_score is not None else "",
        ])
    return response


@login_required
def fraud_center(request):
    _require_fraud_access(request.user)
    payments = _payment_queryset()
    filter_form, payments = _filtered_payments(request, payments, FraudMonitorFilterForm)
    if filter_form.is_valid() and filter_form.cleaned_data.get("case_status"):
        payments = payments.filter(fraud_case__status=filter_form.cleaned_data["case_status"])

    counts = Payment.objects.aggregate(
        total=Count("pk"),
        succeeded=Count("pk", filter=Q(status=Payment.Status.SUCCEEDED)),
        failed=Count("pk", filter=Q(status=Payment.Status.FAILED)),
        held=Count("pk", filter=Q(status=Payment.Status.HELD_FOR_REVIEW)),
        rejected=Count("pk", filter=Q(status=Payment.Status.REJECTED)),
        low_risk=Count("pk", filter=Q(fraud_score__lt=30)),
        medium_risk=Count("pk", filter=Q(fraud_score__gte=30, fraud_score__lt=50)),
        high_risk=Count("pk", filter=Q(fraud_score__gte=50, fraud_score__lt=80)),
        critical_risk=Count("pk", filter=Q(fraud_score__gte=80)),
    )
    risk_total = max(counts["total"], 1)
    risk_distribution = [
        {"label": "Low", "count": counts["low_risk"], "width": int(counts["low_risk"] * 100 / risk_total), "class": "risk-low"},
        {"label": "Medium", "count": counts["medium_risk"], "width": int(counts["medium_risk"] * 100 / risk_total), "class": "risk-medium"},
        {"label": "High", "count": counts["high_risk"], "width": int(counts["high_risk"] * 100 / risk_total), "class": "risk-high"},
        {"label": "Critical", "count": counts["critical_risk"], "width": int(counts["critical_risk"] * 100 / risk_total), "class": "risk-critical"},
    ]
    cases = FraudCase.objects.select_related(
        "payment", "payment__customer", "payment__source_account", "assigned_reviewer"
    ).filter(status__in=[
        FraudCase.Status.NEW, FraudCase.Status.INVESTIGATING, FraudCase.Status.ESCALATED,
    ])
    if filter_form.is_valid() and filter_form.cleaned_data.get("case_status"):
        cases = FraudCase.objects.select_related(
            "payment", "payment__customer", "payment__source_account", "assigned_reviewer"
        ).filter(status=filter_form.cleaned_data["case_status"])
    return render(request, "payments/fraud_center.html", {
        "payments": payments[:50],
        "cases": cases[:20],
        "metrics": counts,
        "risk_distribution": risk_distribution,
        "filter_form": filter_form,
        "filter_query": request.GET.urlencode(),
    })


@login_required
def fraud_case_detail(request, case_id):
    _require_fraud_access(request.user)
    fraud_case = get_object_or_404(
        FraudCase.objects.select_related(
            "payment", "payment__customer", "payment__source_account", "payment__beneficiary",
            "assigned_reviewer",
        ),
        pk=case_id,
    )
    payment_timeline, timeline_duration_ms = _payment_timeline(fraud_case.payment)
    form = FraudCaseUpdateForm(request.POST or None, initial={"status": fraud_case.status})
    if request.method == "POST" and form.is_valid():
        new_status = form.cleaned_data["status"]
        if new_status not in CASE_TRANSITIONS[fraud_case.status]:
            form.add_error("status", "This case cannot transition from its current status.")
        else:
            with transaction.atomic():
                fraud_case = FraudCase.objects.select_for_update().get(pk=fraud_case.pk)
                old_status = fraud_case.status
                if new_status not in CASE_TRANSITIONS[old_status]:
                    form.add_error("status", "This case was updated by another reviewer. Refresh and try again.")
                else:
                    fraud_case.status = new_status
                    fraud_case.assigned_reviewer = request.user
                    fraud_case.save(update_fields=["status", "assigned_reviewer", "updated_at"])
                    AuditEvent.objects.create(
                        actor=request.user,
                        action="FRAUD_CASE_UPDATED",
                        object_type="FraudCase",
                        object_id=str(fraud_case.pk),
                        correlation_id=fraud_case.payment.public_ref,
                        metadata={
                            "from_status": old_status,
                            "to_status": new_status,
                            "note": form.cleaned_data["analyst_note"],
                        },
                    )
                    messages.success(request, "Case update recorded in the audit trail.")
                    return redirect("payments:fraud-case", case_id=fraud_case.pk)

    return render(request, "payments/fraud_case_detail.html", {
        "fraud_case": fraud_case,
        "form": form,
        "payment": fraud_case.payment,
        "payment_timeline": payment_timeline,
        "timeline_duration_ms": timeline_duration_ms,
        "case_history": AuditEvent.objects.filter(
            object_type="FraudCase", object_id=str(fraud_case.pk)
        ).order_by("-created_at", "-pk"),
    })
