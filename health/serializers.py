from sync.serializers import (
    COMMON_SYNC_FIELDS,
    COMMON_SYNC_READ_ONLY_FIELDS,
    SyncableSerializer,
)

from .models import (
    ActivitySample,
    DailyRollup,
    Goal,
    HealthSample,
    Note,
    WorkoutSession,
)


class HealthSampleSerializer(SyncableSerializer):
    class Meta:
        model = HealthSample
        fields = COMMON_SYNC_FIELDS + [
            "metric_type",
            "value",
            "unit",
            "recorded_at",
            "note",
        ]
        read_only_fields = COMMON_SYNC_READ_ONLY_FIELDS


class ActivitySampleSerializer(SyncableSerializer):
    class Meta:
        model = ActivitySample
        fields = COMMON_SYNC_FIELDS + [
            "activity_type",
            "started_at",
            "ended_at",
            "confidence",
            "distance_meters",
            "steps",
        ]
        read_only_fields = COMMON_SYNC_READ_ONLY_FIELDS


class WorkoutSessionSerializer(SyncableSerializer):
    class Meta:
        model = WorkoutSession
        fields = COMMON_SYNC_FIELDS + [
            "activity_type",
            "started_at",
            "ended_at",
            "distance_meters",
            "calories",
            "notes",
        ]
        read_only_fields = COMMON_SYNC_READ_ONLY_FIELDS


class GoalSerializer(SyncableSerializer):
    class Meta:
        model = Goal
        fields = COMMON_SYNC_FIELDS + [
            "metric_type",
            "target_value",
            "period",
            "start_date",
            "end_date",
            "is_active",
        ]
        read_only_fields = COMMON_SYNC_READ_ONLY_FIELDS


class NoteSerializer(SyncableSerializer):
    class Meta:
        model = Note
        fields = COMMON_SYNC_FIELDS + ["content", "note_date", "context"]
        read_only_fields = COMMON_SYNC_READ_ONLY_FIELDS


class DailyRollupSerializer(SyncableSerializer):
    class Meta:
        model = DailyRollup
        fields = COMMON_SYNC_FIELDS + [
            "date",
            "steps",
            "distance_meters",
            "active_minutes",
            "calories",
            "floors",
        ]
        read_only_fields = fields
