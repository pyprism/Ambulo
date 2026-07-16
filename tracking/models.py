from django.db import models

from sync.models import SyncableModel
from utils.enums import Connectivity, MonitoringMode, PlaceCategory


class LocationPoint(SyncableModel):
    latitude = models.FloatField()
    longitude = models.FloatField()
    altitude = models.FloatField(null=True, blank=True)
    horizontal_accuracy = models.FloatField(null=True, blank=True)
    vertical_accuracy = models.FloatField(null=True, blank=True)
    speed = models.FloatField(null=True, blank=True)
    heading = models.FloatField(null=True, blank=True)
    recorded_at = models.DateTimeField()
    battery_level = models.PositiveSmallIntegerField(null=True, blank=True)
    connectivity = models.CharField(
        max_length=16, choices=Connectivity.choices, default=Connectivity.unknown
    )
    monitoring_mode = models.CharField(
        max_length=16, choices=MonitoringMode.choices, default=MonitoringMode.manual
    )

    class Meta(SyncableModel.Meta):
        indexes = [models.Index(fields=["user", "recorded_at"])]


class Place(SyncableModel):
    """User-defined region / geofence ."""

    name = models.CharField(max_length=255)
    category = models.CharField(
        max_length=16, choices=PlaceCategory.choices, default=PlaceCategory.custom
    )
    latitude = models.FloatField()
    longitude = models.FloatField()
    radius_meters = models.FloatField(default=100)
    address = models.CharField(max_length=500, blank=True)
    currently_inside = models.BooleanField(default=False)
    last_entered_at = models.DateTimeField(null=True, blank=True)
    last_exited_at = models.DateTimeField(null=True, blank=True)
    state_as_of = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "recorded_at of the point that last determined currently_inside. "
            "Guards against out-of-order/concurrent geofence tasks (batch "
            "sync, retries) flipping state using a stale point."
        ),
    )

    class Meta(SyncableModel.Meta):
        indexes = [models.Index(fields=["user", "category"])]


class Trip(SyncableModel):
    """Client recorded route (client groups points into a trip while
    tracking, server just stores the container)."""

    name = models.CharField(max_length=255, blank=True)
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    distance_meters = models.FloatField(default=0)
    point_count = models.PositiveIntegerField(default=0)
    start_place = models.ForeignKey(
        Place,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="trips_started",
    )
    end_place = models.ForeignKey(
        Place,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="trips_ended",
    )

    class Meta(SyncableModel.Meta):
        indexes = [models.Index(fields=["user", "started_at"])]
