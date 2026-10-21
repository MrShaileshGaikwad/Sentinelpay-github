from .permissions import user_can_review_fraud


def fraud_access(request):
    return {"can_review_fraud": user_can_review_fraud(request.user)}
