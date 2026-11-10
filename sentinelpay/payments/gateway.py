"""
SIMULATOR ONLY. This module never contacts a payment network.

The merchant code selects the outcome, so every demo and test is deterministic.
"""
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class GatewayOutcome(Enum):
    SUCCESS = "SUCCESS"
    DECLINED = "DECLINED"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"


# merchant_code -> (display name, outcome the simulator returns)
SIMULATOR_MERCHANTS = {
    "SIM-GROCERY": ("Sandbox Grocery Store", GatewayOutcome.SUCCESS),
    "SIM-DECLINE": ("Sandbox Declining Merchant", GatewayOutcome.DECLINED),
    "SIM-TIMEOUT": ("Sandbox Slow Merchant", GatewayOutcome.TIMEOUT),
    "SIM-ERROR": ("Sandbox Faulty Merchant", GatewayOutcome.ERROR),
}


@dataclass(frozen=True)
class GatewayResponse:
    outcome: GatewayOutcome
    code: str


class SimulatedGateway:
    def submit(self, merchant_code: str, amount: Decimal, reference: str) -> GatewayResponse:
        if merchant_code not in SIMULATOR_MERCHANTS:
            return GatewayResponse(GatewayOutcome.ERROR, "SIM_UNKNOWN_MERCHANT")
        _, outcome = SIMULATOR_MERCHANTS[merchant_code]
        return GatewayResponse(outcome, f"SIM_{outcome.value}")
