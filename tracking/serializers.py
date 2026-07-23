from rest_framework import serializers

from sync.serializers import (
    COMMON_SYNC_FIELDS,
    COMMON_SYNC_READ_ONLY_FIELDS,
    SyncableSerializer,
)

from .models import LocationPoint, Place, Trip


class LatLonValidationMixin:
    """Shared by LocationPointSerializer and PlaceSerializer — both accept
    raw lat/lon with no range check today, so latitude 999 or a negative
    geofence radius currently persists fine."""

    def validate_latitude(self, value):
        if not -90 <= value <= 90:
            raise serializers.ValidationError("latitude must be between -90 and 90.")
        return value

    def validate_longitude(self, value):
        if not -180 <= value <= 180:
            raise serializers.ValidationError("longitude must be between -180 and 180.")
        return value


class LocationPointSerializer(LatLonValidationMixin, SyncableSerializer):
    class Meta:
        model = LocationPoint
        fields = COMMON_SYNC_FIELDS + [
            "latitude",
            "longitude",
            "altitude",
            "horizontal_accuracy",
            "vertical_accuracy",
            "speed",
            "heading",
            "recorded_at",
            "battery_level",
            "connectivity",
            "monitoring_mode",
        ]
        read_only_fields = COMMON_SYNC_READ_ONLY_FIELDS

    def validate_horizontal_accuracy(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError(
                "horizontal_accuracy must be non-negative."
            )
        return value

    def validate_vertical_accuracy(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("vertical_accuracy must be non-negative.")
        return value

    def validate_speed(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("speed must be non-negative.")
        return value

    def validate_heading(self, value):
        if value is not None and not 0 <= value < 360:
            raise serializers.ValidationError("heading must be between 0 and 360.")
        return value

    def validate_battery_level(self, value):
        if value is not None and not 0 <= value <= 100:
            raise serializers.ValidationError(
                "battery_level must be between 0 and 100."
            )
        return value


class PlaceSerializer(LatLonValidationMixin, SyncableSerializer):
    class Meta:
        model = Place
        fields = COMMON_SYNC_FIELDS + [
            "name",
            "category",
            "latitude",
            "longitude",
            "radius_meters",
            "address",
            "currently_inside",
            "last_entered_at",
            "last_exited_at",
            "notify_friends",
        ]
        read_only_fields = COMMON_SYNC_READ_ONLY_FIELDS + [
            "currently_inside",
            "last_entered_at",
            "last_exited_at",
        ]

    def validate_radius_meters(self, value):
        if value <= 0:
            raise serializers.ValidationError("radius_meters must be positive.")
        return value


class TripSerializer(SyncableSerializer):
    start_place = serializers.PrimaryKeyRelatedField(
        queryset=Place.objects.all(), required=False, allow_null=True
    )
    end_place = serializers.PrimaryKeyRelatedField(
        queryset=Place.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = Trip
        fields = COMMON_SYNC_FIELDS + [
            "name",
            "started_at",
            "ended_at",
            "distance_meters",
            "point_count",
            "start_place",
            "end_place",
        ]
        read_only_fields = COMMON_SYNC_READ_ONLY_FIELDS

    def validate(self, attrs):
        """Reject a start_place/end_place id owned by another user
        — requires context={"request": request}."""
        request = self.context.get("request")
        if request is not None:
            for field in ("start_place", "end_place"):
                place = attrs.get(field)
                if place is not None and place.user_id != request.user.id:
                    raise serializers.ValidationError({field: "Place not found."})
        return attrs
