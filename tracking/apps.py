from django.apps import AppConfig


class TrackingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tracking"

    def ready(self):
        from sync.registry import register_syncable

        from . import signals  # noqa: F401
        from .models import LocationPoint, Place, Trip
        from .serializers import (
            LocationPointSerializer,
            PlaceSerializer,
            TripSerializer,
        )

        register_syncable("location_point", LocationPoint, LocationPointSerializer)
        register_syncable("place", Place, PlaceSerializer)
        register_syncable("trip", Trip, TripSerializer)
