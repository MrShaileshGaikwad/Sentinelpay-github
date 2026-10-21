FRAUD_ANALYST_GROUP = "Fraud Analysts"


def user_can_review_fraud(user):
    return bool(
        user.is_authenticated
        and (
            user.is_staff
            or user.is_superuser
            or user.groups.filter(name=FRAUD_ANALYST_GROUP).exists()
        )
    )
