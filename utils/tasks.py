import logging

logger = logging.getLogger(__name__)


def safe_delay(task, *args, **kwargs):
    """Fire-and-forget a Celery task without letting a broker outage break
    the synchronous request that triggered it (e.g. a post_save signal)."""
    try:
        return task.delay(*args, **kwargs)
    except Exception:
        logger.exception("Failed to dispatch task %s", getattr(task, "name", task))
        return None
