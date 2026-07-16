from django.db import models

from sync.models import SyncableModel
from utils.enums import ActivityType, GoalPeriod, HealthMetricType


class HealthSample(SyncableModel):
    """Phone-sensor or manually-entered health metric."""

    metric_type = models.CharField(max_length=32, choices=HealthMetricType.choices)
    value = models.FloatField()
    unit = models.CharField(max_length=32, blank=True)
    recorded_at = models.DateTimeField()
    note = models.TextField(blank=True)

    class Meta(SyncableModel.Meta):
        indexes = [models.Index(fields=["user", "metric_type", "recorded_at"])]


class ActivitySample(SyncableModel):
    """Detected activity segment (still/walking/running/cycling/vehicle)."""

    activity_type = models.CharField(max_length=16, choices=ActivityType.choices)
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    confidence = models.FloatField(null=True, blank=True)
    distance_meters = models.FloatField(null=True, blank=True)
    steps = models.PositiveIntegerField(null=True, blank=True)

    class Meta(SyncableModel.Meta):
        indexes = [models.Index(fields=["user", "started_at"])]


class WorkoutSession(SyncableModel):
    activity_type = models.CharField(max_length=16, choices=ActivityType.choices)
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    distance_meters = models.FloatField(null=True, blank=True)
    calories = models.FloatField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta(SyncableModel.Meta):
        indexes = [models.Index(fields=["user", "started_at"])]


class Goal(SyncableModel):
    metric_type = models.CharField(max_length=32, choices=HealthMetricType.choices)
    target_value = models.FloatField()
    period = models.CharField(
        max_length=16, choices=GoalPeriod.choices, default=GoalPeriod.daily
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta(SyncableModel.Meta):
        indexes = [models.Index(fields=["user", "is_active"])]


class Note(SyncableModel):
    content = models.TextField()
    note_date = models.DateField()
    context = models.CharField(max_length=32, blank=True)

    class Meta(SyncableModel.Meta):
        indexes = [models.Index(fields=["user", "note_date"])]


class DailyRollup(SyncableModel):
    """Server-computed daily aggregate (Celery task, not client-writable —
    intentionally not registered in sync.registry so it can't be spoofed via
    the generic /sync/upload surface; read-only via /api/stats/)."""

    date = models.DateField()
    steps = models.PositiveIntegerField(default=0)
    distance_meters = models.FloatField(default=0)
    active_minutes = models.PositiveIntegerField(default=0)
    calories = models.FloatField(default=0)
    floors = models.PositiveIntegerField(default=0)

    class Meta(SyncableModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["user", "date"], name="unique_daily_rollup_per_user_date"
            )
        ]
