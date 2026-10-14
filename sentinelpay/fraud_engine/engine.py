"""
Deterministic, rule-based fraud scoring. Pure Python with no Django dependency.

Each rule is a pure function returning a RuleResult. The engine sums points,
caps the total at 100, and maps the score to a decision via decide().
The score is an educational convention, not a calibrated fraud probability.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Callable

RULESET_VERSION = "1.0.0"

HIGH_AMOUNT_LIMIT = Decimal("100000.00")  # R-01
AMOUNT_RATIO_LIMIT = Decimal("3.0")       # R-02: amount vs 30-day successful average
VELOCITY_LIMIT_PER_HOUR = 5               # R-03
FAILED_ATTEMPTS_LIMIT = 3                 # R-04
NEW_BENEFICIARY_WINDOW_HOURS = 24         # R-05
NIGHT_START_HOUR, NIGHT_END_HOUR = 0, 4   # R-06: 00:00 to 04:59 local time
DECLINE_AT = 80
REVIEW_AT = 50
STEP_UP_AT = 30


@dataclass(frozen=True)
class PaymentContext:
    amount: Decimal
    customer_avg_amount_30d: Decimal
    payments_last_hour: int
    failed_attempts_last_hour: int
    beneficiary_added_at: datetime | None
    payment_time: datetime
    is_new_device: bool
    ip_country: str
    home_country: str


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    triggered: bool
    points: int
    explanation: str


@dataclass
class Evaluation:
    score: int
    decision: str
    band: str
    results: list[RuleResult] = field(default_factory=list)
    ruleset_version: str = RULESET_VERSION

    @property
    def triggered_rules(self) -> list[RuleResult]:
        return [r for r in self.results if r.triggered]


def r01_high_amount(ctx: PaymentContext) -> RuleResult:
    hit = ctx.amount >= HIGH_AMOUNT_LIMIT
    return RuleResult("R-01", hit, 30 if hit else 0,
                      f"Amount {ctx.amount} is at or above the high-amount limit {HIGH_AMOUNT_LIMIT}.")


def r02_amount_spike(ctx: PaymentContext) -> RuleResult:
    if ctx.customer_avg_amount_30d <= 0:
        return RuleResult("R-02", False, 0, "No 30-day successful history; rule skipped.")
    ratio = ctx.amount / ctx.customer_avg_amount_30d
    hit = ratio >= AMOUNT_RATIO_LIMIT
    return RuleResult("R-02", hit, 20 if hit else 0,
                      f"Amount is {ratio:.1f}x the 30-day average (limit {AMOUNT_RATIO_LIMIT}x).")


def r03_velocity(ctx: PaymentContext) -> RuleResult:
    hit = ctx.payments_last_hour >= VELOCITY_LIMIT_PER_HOUR
    return RuleResult("R-03", hit, 15 if hit else 0,
                      f"{ctx.payments_last_hour} payments in the last hour (limit {VELOCITY_LIMIT_PER_HOUR}).")


def r04_failed_attempts(ctx: PaymentContext) -> RuleResult:
    hit = ctx.failed_attempts_last_hour >= FAILED_ATTEMPTS_LIMIT
    return RuleResult("R-04", hit, 20 if hit else 0,
                      f"{ctx.failed_attempts_last_hour} failed or rejected attempts in the last hour.")


def r05_new_beneficiary(ctx: PaymentContext) -> RuleResult:
    if ctx.beneficiary_added_at is None:
        return RuleResult("R-05", False, 0, "No beneficiary linked to this payment.")
    age_hours = (ctx.payment_time - ctx.beneficiary_added_at).total_seconds() / 3600
    hit = 0 <= age_hours < NEW_BENEFICIARY_WINDOW_HOURS
    return RuleResult("R-05", hit, 15 if hit else 0, f"Beneficiary was added {age_hours:.1f} hours ago.")


def r06_night_time(ctx: PaymentContext) -> RuleResult:
    hit = NIGHT_START_HOUR <= ctx.payment_time.hour <= NIGHT_END_HOUR
    return RuleResult("R-06", hit, 10 if hit else 0,
                      f"Payment initiated at {ctx.payment_time:%H:%M}, within the unusual-hours window.")


def r07_new_device(ctx: PaymentContext) -> RuleResult:
    return RuleResult("R-07", ctx.is_new_device, 15 if ctx.is_new_device else 0,
                      "Payment from a device not previously seen for this customer.")


def r08_foreign_ip(ctx: PaymentContext) -> RuleResult:
    hit = ctx.ip_country != ctx.home_country
    return RuleResult("R-08", hit, 15 if hit else 0,
                      f"Request IP country {ctx.ip_country} differs from home country {ctx.home_country}.")


RULES: list[Callable[[PaymentContext], RuleResult]] = [
    r01_high_amount, r02_amount_spike, r03_velocity, r04_failed_attempts,
    r05_new_beneficiary, r06_night_time, r07_new_device, r08_foreign_ip,
]


def decide(score: int) -> tuple[str, str]:
    """Map a score to (decision, band). Ordered from most to least severe."""
    if score >= DECLINE_AT:
        return "DECLINE", "HIGH"
    if score >= REVIEW_AT:
        return "REVIEW", "ELEVATED"
    if score >= STEP_UP_AT:
        return "STEP_UP", "MODERATE"
    return "APPROVE", "LOW"


def evaluate(ctx: PaymentContext) -> Evaluation:
    results = [rule(ctx) for rule in RULES]
    score = min(100, sum(r.points for r in results))
    decision, band = decide(score)
    return Evaluation(score=score, decision=decision, band=band, results=results)
