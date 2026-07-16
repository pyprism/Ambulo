from sync.viewsets import SyncableModelViewSet

from .models import LocationPoint, Place, Trip
from .serializers import LocationPointSerializer, PlaceSerializer, TripSerializer


class LocationPointViewSet(SyncableModelViewSet):
    """Batch, idempotent LocationPoint ingest ."""

    model = LocationPoint
    serializer_class = LocationPointSerializer
    filterset_fields = ["monitoring_mode", "connectivity"]


class PlaceViewSet(SyncableModelViewSet):
    model = Place
    serializer_class = PlaceSerializer
    filterset_fields = ["category"]


class TripViewSet(SyncableModelViewSet):
    model = Trip
    serializer_class = TripSerializer
