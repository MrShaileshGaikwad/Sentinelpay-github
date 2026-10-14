from datetime import datetime
from decimal import Decimal

from fraud_engine.engine import PaymentContext, decide, evaluate

BASE = dict(
    amount=Decimal("500.00"),
    customer_avg_amount_30d=Decimal("600.00"),
    payments_last_hour=1,
    failed_attempts_last_hour=0,
    beneficiary_added_at=None,
    payment_time=datetime(2026, 10, 17, 14, 0),
    is_new_device=False,
    ip_country="IN",
    home_country="IN",
)


def ctx(**overrides):
    return PaymentContext(**{**BASE, **overrides})


def test_normal_payment_is_approved():
    result = evaluate(ctx())
    assert result.score == 0
    assert result.decision == "APPROVE"


def test_high_amount_scores_30():
    result = evaluate(ctx(amount=Decimal("150000.00")))
    assert "R-01" in [r.rule_id for r in result.triggered_rules]
    assert result.score >= 30


def test_decision_boundaries():
    assert decide(29)[0] == "APPROVE"
    assert decide(30)[0] == "STEP_UP"
    assert decide(49)[0] == "STEP_UP"
    assert decide(50)[0] == "REVIEW"
    assert decide(79)[0] == "REVIEW"
    assert decide(80)[0] == "DECLINE"


def test_score_is_capped_at_100():
    risky = ctx(
        amount=Decimal("900000.00"),
        payments_last_hour=20,
        failed_attempts_last_hour=10,
        beneficiary_added_at=datetime(2026, 10, 17, 13, 0),
        payment_time=datetime(2026, 10, 17, 2, 0),
        is_new_device=True,
        ip_country="RU",
    )
    assert evaluate(risky).score == 100


def test_night_window_is_inclusive_of_04_and_exclusive_of_05():
    assert "R-06" in [r.rule_id for r in evaluate(ctx(payment_time=datetime(2026, 10, 17, 4, 59))).triggered_rules]
    assert "R-06" not in [r.rule_id for r in evaluate(ctx(payment_time=datetime(2026, 10, 17, 5, 0))).triggered_rules]


def test_every_triggered_rule_has_explanation():
    for r in evaluate(ctx(failed_attempts_last_hour=4)).triggered_rules:
        assert r.explanation
