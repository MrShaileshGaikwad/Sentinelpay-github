"""
Payment state machine. The only path to changing a payment's status.
Terminal states have no outgoing transitions. UNKNOWN is resolved only by a
reconciliation workflow, which is not built in this slice.
"""
from .models import Payment

Status = Payment.Status

ALLOWED_TRANSITIONS = {
    Status.INITIATED: {Status.REJECTED, Status.HELD_FOR_REVIEW, Status.SUBMITTED},
    Status.SUBMITTED: {Status.SUCCEEDED, Status.FAILED, Status.UNKNOWN},
    Status.UNKNOWN: set(),
    Status.HELD_FOR_REVIEW: set(),
    Status.REJECTED: set(),
    Status.SUCCEEDED: set(),
    Status.FAILED: set(),
}


class InvalidTransition(Exception):
    pass


def transition(payment: Payment, new_status: str) -> None:
    current = Status(payment.status)
    if Status(new_status) not in ALLOWED_TRANSITIONS[current]:
        raise InvalidTransition(f"Cannot move payment from {current.value} to {new_status}.")
    payment.status = new_status
    payment.save(update_fields=["status", "updated_at"])
