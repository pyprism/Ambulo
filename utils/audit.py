from accounts.models import AuditLog


def record_audit_event(request, action, **metadata):
    """Log a security-relevant event. Never raises —
    a logging failure must not break the request that triggered it."""

    try:
        user = getattr(request, "user", None)
        if not getattr(user, "is_authenticated", False):
            user = None
        AuditLog.objects.create(
            user=user,
            action=action,
            metadata=metadata,
            ip_address=request.META.get("REMOTE_ADDR"),
        )
    except Exception:
        import logging

        logging.getLogger(__name__).exception("Failed to record audit event %s", action)
