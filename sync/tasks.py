from celery import shared_task
from django.utils import timezone


@shared_task(name="sync.ping")
def ping():
    """Trivial worker liveness probe consumed by the /healthz endpoint."""
    return timezone.now().isoformat()
