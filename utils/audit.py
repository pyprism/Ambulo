from django.conf import settings

from accounts.models import AuditLog


def client_ip_address(request):
    """Use forwarding headers only when the direct peer is explicitly trusted.

    Deployments behind nginx/Cloudflare must set TRUSTED_PROXY_IPS to their
    immediate proxy addresses and configure nginx to replace X-Forwarded-For.
    """
    remote_addr = request.META.get("REMOTE_ADDR")
    trusted = set(getattr(settings, "TRUSTED_PROXY_IPS", ()))
    if remote_addr not in trusted:
        return remote_addr
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return remote_addr


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
            ip_address=client_ip_address(request),
        )
    except Exception:
        import logging

        logging.getLogger(__name__).exception("Failed to record audit event %s", action)
