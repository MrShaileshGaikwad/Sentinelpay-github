from .models import Customer
from .permissions import user_can_review_fraud


def fraud_access(request):
    return {"can_review_fraud": user_can_review_fraud(request.user)}


def customer_identity(request):
    account_name = request.user.get_username()
    if request.user.is_authenticated:
        try:
            profile = request.user.customer_profile
        except Customer.DoesNotExist:
            pass
        else:
            account_name = profile.full_name or account_name
    return {"account_display_name": account_name}
