from datetime import datetime, timezone as datetime_timezone

from rest_framework import status
from rest_framework.authentication import BasicAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from sync.views import SyncableModelViewSet
from utils.enums import SyncSource

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


class OwnTracksIngestView(APIView):
    """Accept the official OwnTracks HTTP location payload at /api/pub/."""

    authentication_classes = [BasicAuthentication, *APIView.authentication_classes]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        payload = request.data
        if not isinstance(payload, dict) or payload.get("_type") != "location":
            return Response(
                {"message": "Expected an OwnTracks location payload."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            latitude, longitude = float(payload["lat"]), float(payload["lon"])
            if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                raise ValueError
            recorded_at = datetime.fromtimestamp(
                float(payload["tst"]), tz=datetime_timezone.utc
            )
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            return Response(
                {"message": "lat, lon, and tst must be valid OwnTracks values."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        point = LocationPoint.objects.create(
            user=request.user,
            latitude=latitude,
            longitude=longitude,
            recorded_at=recorded_at,
            altitude=payload.get("alt"),
            horizontal_accuracy=payload.get("acc"),
            speed=payload.get("vel"),
            heading=payload.get("cog"),
            battery_level=payload.get("batt"),
            source=SyncSource.location,
        )
        return Response(
            LocationPointSerializer(point).data, status=status.HTTP_201_CREATED
        )
