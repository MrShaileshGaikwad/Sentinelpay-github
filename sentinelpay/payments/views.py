import uuid

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render

from .forms import PaymentForm
from .models import Payment
from .services import IdempotencyConflict, InsufficientFunds, PaymentError, create_payment


@login_required
def payment_create(request):
    if request.method == "POST":
        form = PaymentForm(request.POST, user=request.user)
        if form.is_valid():
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
                return redirect("payments:detail", public_ref=payment.public_ref)
    else:
        form = PaymentForm(user=request.user, initial={"idempotency_key": str(uuid.uuid4())})
    return render(request, "payments/payment_form.html", {"form": form})


@login_required
def payment_detail(request, public_ref):
    # Ownership is enforced in the query. Another customer's payment returns 404, not 403.
    payment = get_object_or_404(Payment, public_ref=public_ref, customer=request.user)
    return render(request, "payments/payment_detail.html", {
        "payment": payment,
        "ledger_entries": payment.ledger_entries.all(),
    })


@login_required
def payment_list(request):
    payments = Payment.objects.filter(customer=request.user).select_related("source_account")
    page_obj = Paginator(payments, 20).get_page(request.GET.get("page"))
    return render(request, "payments/transaction_list.html", {"page_obj": page_obj})
