from rest_framework.routers import DefaultRouter

from .views import (
    ActivitySampleViewSet,
    GoalViewSet,
    HealthSampleViewSet,
    NoteViewSet,
    StatsViewSet,
    WorkoutSessionViewSet,
)

router = DefaultRouter()
router.register("health-samples", HealthSampleViewSet, basename="health-sample")
router.register("activity-samples", ActivitySampleViewSet, basename="activity-sample")
router.register("workouts", WorkoutSessionViewSet, basename="workout-session")
router.register("goals", GoalViewSet, basename="goal")
router.register("notes", NoteViewSet, basename="note")
router.register("stats", StatsViewSet, basename="stats")

urlpatterns = router.urls
