from datetime import date as date_cls
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from utils.enums import HealthMetricType

from .models import DailyRollup, HealthSample

ROLLUP_METRIC_FIELDS = {
    HealthMetricType.steps: "steps",
    HealthMetricType.distance: "distance_meters",
    HealthMetricType.active_minutes: "active_minutes",
    HealthMetricType.calories: "calories",
    HealthMetricType.floors: "floors",
}


@shared_task(name="health.compute_daily_rollup")
def compute_daily_rollup(user_id, date_iso):
    """Sum a user's HealthSample values for one day into their DailyRollup."""
    target_date = date_cls.fromisoformat(date_iso)
    samples = HealthSample.objects.filter(
        user_id=user_id,
        recorded_at__date=target_date,
        metric_type__in=ROLLUP_METRIC_FIELDS,
        deleted_at__isnull=True,
    )
    totals = {field: 0 for field in ROLLUP_METRIC_FIELDS.values()}
    for sample in samples:
        field = ROLLUP_METRIC_FIELDS.get(sample.metric_type)
        if field:
            totals[field] += sample.value

    # select_for_update + an explicit outer atomic serializes concurrent
    # rollups for the same (user, date) — compute_daily_rollup is callable
    # both from the nightly sweep and ad hoc, so two runs can overlap
    with transaction.atomic():
        rollup, created = DailyRollup.objects.select_for_update().get_or_create(
            user_id=user_id, date=target_date, defaults={"source": "server", **totals}
        )
        if not created:
            for field, value in totals.items():
                setattr(rollup, field, value)
            rollup.save()
    return str(rollup.pk)


@shared_task(name="health.recompute_recent_rollups")
def recompute_recent_rollups(days=2):
    """Nightly sweep: re-aggregate any (user, day) with HealthSample writes
    in the last ``days`` days. Self-healing catch-up instead of triggering a
    rollup task on every single sample write.

    Deliberately does NOT filter out tombstoned samples here — a deletion
    is exactly the kind of "write" that must re-trigger the day's rollup
    (compute_daily_rollup itself still excludes deleted rows from the sum).
    Filtering them out here meant a deleted sample's day was never
    re-queued and the rollup kept the stale, pre-deletion total.
    """
    since = timezone.now() - timedelta(days=days)
    pairs = (
        HealthSample.objects.filter(updated_at__gte=since)
        .values_list("user_id", "recorded_at__date")
        .distinct()
    )
    count = 0
    for user_id, sample_date in pairs:
        compute_daily_rollup.delay(user_id, sample_date.isoformat())
        count += 1
    return count
