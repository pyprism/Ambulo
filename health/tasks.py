from datetime import date as date_cls
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.db.models import Max, Sum
from django.utils import timezone

from utils.enums import HealthMetricType, SyncSource

from .models import DailyRollup, HealthSample

ROLLUP_METRIC_FIELDS = {
    HealthMetricType.steps: "steps",
    HealthMetricType.distance: "distance_meters",
    HealthMetricType.active_minutes: "active_minutes",
    HealthMetricType.calories: "calories",
    HealthMetricType.floors: "floors",
}

# Sources whose writers guarantee at most one row per device per metric per
# day — the pedometer (motion) upserts in place, and Health Connect imports
# (health) use a day-deterministic id — so a per-device max collapses
# duplicate multi-device reports of the same activity without losing data.
# Manual entries (and anything else, including "import") carry no such
# guarantee — a user can log two separate walks the same day — and must be
# summed instead, or a second entry silently replaces the first rather than
# adding to it. "import" is currently safe to leave out of this list: the
# only parser that emits health_sample rows (parse_tcx, for heart_rate) never
# writes a metric in ROLLUP_METRIC_FIELDS, so no import-sourced row is ever
# summed today. If a future parser emits steps/distance/calories/etc, decide
# then whether it belongs here (Health Connect/pedometer overlap risk — see
# _stepsCutoffDate on the client) or in the summed bucket.
_DEDUPED_SOURCES = [SyncSource.motion, SyncSource.health]


@shared_task(name="health.compute_daily_rollup")
def compute_daily_rollup(user_id, date_iso):
    """Sum a user's HealthSample values for one day into their DailyRollup.

    Day bucketing uses ``recorded_at__date``, i.e. the server's
    ``settings.TIME_ZONE`` — not the user's local day. Clients write
    per-local-day rows, so a user several zones away from the server can get
    samples split across the wrong rollup day. Documented server-TZ
    semantics for now; per-user timezone bucketing is a bigger migration +
    client contract change, tracked separately.
    """
    target_date = date_cls.fromisoformat(date_iso)
    samples = HealthSample.objects.filter(
        user_id=user_id,
        recorded_at__date=target_date,
        metric_type__in=ROLLUP_METRIC_FIELDS,
        deleted_at__isnull=True,
    )
    totals = {}
    for metric_type, field in ROLLUP_METRIC_FIELDS.items():
        day_samples = samples.filter(metric_type=metric_type)
        sensor_total = max(
            day_samples.filter(source__in=_DEDUPED_SOURCES)
            .values("device_id")
            .annotate(value=Max("value"))
            .values_list("value", flat=True),
            default=0,
        )
        manual_total = (
            day_samples.exclude(source__in=_DEDUPED_SOURCES).aggregate(
                total=Sum("value")
            )["total"]
            or 0
        )
        totals[field] = sensor_total + manual_total

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
