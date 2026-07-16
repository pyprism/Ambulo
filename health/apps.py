from django.apps import AppConfig


class HealthConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "health"

    def ready(self):
        from sync.registry import register_syncable

        from .models import ActivitySample, Goal, HealthSample, Note, WorkoutSession
        from .serializers import (
            ActivitySampleSerializer,
            GoalSerializer,
            HealthSampleSerializer,
            NoteSerializer,
            WorkoutSessionSerializer,
        )

        register_syncable("health_sample", HealthSample, HealthSampleSerializer)
        register_syncable("activity_sample", ActivitySample, ActivitySampleSerializer)
        register_syncable("workout_session", WorkoutSession, WorkoutSessionSerializer)
        register_syncable("goal", Goal, GoalSerializer)
        register_syncable("note", Note, NoteSerializer)
