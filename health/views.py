from datetime import date, timedelta

from django.db.models import Avg, Sum
from django.db.models.functions import TruncDate
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from sync.views import SyncableModelViewSet
from utils.enums import HealthMetricType

from .models import (
    ActivitySample,
    DailyRollup,
    Goal,
    HealthSample,
    Note,
    WorkoutSession,
)
from .serializers import (
    ActivitySampleSerializer,
    DailyRollupSerializer,
    GoalSerializer,
    HealthSampleSerializer,
    NoteSerializer,
    WorkoutSessionSerializer,
)


class HealthSampleViewSet(SyncableModelViewSet):
    model = HealthSample
    serializer_class = HealthSampleSerializer
    filterset_fields = ["metric_type"]


class ActivitySampleViewSet(SyncableModelViewSet):
    model = ActivitySample
    serializer_class = ActivitySampleSerializer
    filterset_fields = ["activity_type"]


class WorkoutSessionViewSet(SyncableModelViewSet):
    model = WorkoutSession
    serializer_class = WorkoutSessionSerializer
    filterset_fields = ["activity_type"]


class GoalViewSet(SyncableModelViewSet):
    model = Goal
    serializer_class = GoalSerializer
    filterset_fields = ["metric_type", "period", "is_active"]


class NoteViewSet(SyncableModelViewSet):
    model = Note
    serializer_class = NoteSerializer
    filterset_fields = ["context"]


ROLLUP_METRIC_FIELDS = {
    HealthMetricType.steps: "steps",
    HealthMetricType.distance: "distance_meters",
    HealthMetricType.active_minutes: "active_minutes",
    HealthMetricType.calories: "calories",
    HealthMetricType.floors: "floors",
}
SUMMARY_PERIOD_DAYS = {"today": 0, "week": 7, "month": 30, "year": 365}


class StatsViewSet(viewsets.GenericViewSet):
    """Read-only fitness stats: range queries, trends, summaries.
    DailyRollup is server-computed only — never accepted
    via the generic sync/upload surface (see health.models.DailyRollup)."""

    serializer_class = DailyRollupSerializer

    def get_queryset(self):
        return DailyRollup.objects.for_user(self.request.user)

    def _parse_range(self, request, default_days=30):
        today = date.today()
        start = request.query_params.get("start")
        end = request.query_params.get("end")
        try:
            start_date = (
                date.fromisoformat(start)
                if start
                else today - timedelta(days=default_days)
            )
            end_date = date.fromisoformat(end) if end else today
        except ValueError:
            raise ValidationError({"message": "start/end must be YYYY-MM-DD dates."})
        return start_date, end_date

    @action(detail=False, methods=["get"])
    def daily(self, request):
        """Daily rollups by range, or by ?since=<server_rev> cursor."""
        qs = self.get_queryset()
        since = request.query_params.get("since")
        if since:
            try:
                since = int(since)
            except ValueError:
                raise ValidationError(
                    {"message": "since must be an integer server_rev."}
                )
            qs = qs.changed_since(since)
        else:
            start_date, end_date = self._parse_range(request)
            qs = qs.filter(date__gte=start_date, date__lte=end_date).order_by("date")
        page = self.paginate_queryset(qs)
        serializer = self.get_serializer(page if page is not None else qs, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def summary(self, request):
        period = request.query_params.get("period", "week")
        today = date.today()
        start_date = today - timedelta(days=SUMMARY_PERIOD_DAYS.get(period, 7))
        totals = (
            self.get_queryset()
            .filter(date__gte=start_date, date__lte=today)
            .aggregate(
                steps=Sum("steps"),
                distance_meters=Sum("distance_meters"),
                active_minutes=Sum("active_minutes"),
                calories=Sum("calories"),
                floors=Sum("floors"),
            )
        )
        return Response(
            {
                "period": period,
                "start": start_date,
                "end": today,
                **{key: value or 0 for key, value in totals.items()},
            }
        )

    @action(detail=False, methods=["get"])
    def trend(self, request):
        metric = request.query_params.get("metric", HealthMetricType.steps)
        start_date, end_date = self._parse_range(request)
        if metric in ROLLUP_METRIC_FIELDS:
            field = ROLLUP_METRIC_FIELDS[metric]
            rows = (
                self.get_queryset()
                .filter(date__gte=start_date, date__lte=end_date)
                .order_by("date")
                .values("date", field)
            )
            points = [{"date": row["date"], "value": row[field]} for row in rows]
        else:
            # Point-in-time metrics (weight/sleep/mood/heart_rate/...) get a
            # daily average, computed in the DB rather than pulled row-by-row
            # into Python — matters once a metric has years of samples.
            rows = (
                HealthSample.objects.for_user(request.user)
                .not_deleted()
                .filter(
                    metric_type=metric,
                    recorded_at__date__gte=start_date,
                    recorded_at__date__lte=end_date,
                )
                .annotate(day=TruncDate("recorded_at"))
                .values("day")
                .annotate(value=Avg("value"))
                .order_by("day")
            )
            points = [{"date": row["day"], "value": row["value"]} for row in rows]
        return Response({"metric": metric, "points": points})
