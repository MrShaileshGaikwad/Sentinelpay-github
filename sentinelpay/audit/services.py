from .models import AuditEvent


def record_event(*, action, actor=None, object_type="", object_id="", correlation_id=None, metadata=None):
    return AuditEvent.objects.create(
        actor=actor,
        action=action,
        object_type=object_type,
        object_id=str(object_id),
        correlation_id=correlation_id,
        metadata=metadata or {},
    )
