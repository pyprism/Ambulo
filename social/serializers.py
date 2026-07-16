from rest_framework import serializers

from .models import Friendship, Notification


class FriendshipSerializer(serializers.ModelSerializer):
    requester = serializers.CharField(source="requester.username", read_only=True)
    addressee = serializers.CharField(source="addressee.username", read_only=True)
    blocked_by = serializers.CharField(
        source="blocked_by.username", read_only=True, default=None
    )

    class Meta:
        model = Friendship
        fields = [
            "id",
            "requester",
            "addressee",
            "status",
            "requester_shares_location",
            "addressee_shares_location",
            "blocked_by",
            "created_at",
            "updated_at",
            "responded_at",
        ]
        read_only_fields = fields


class FriendRequestSerializer(serializers.Serializer):
    username = serializers.CharField(required=False)
    share_code = serializers.CharField(required=False)

    def validate(self, attrs):
        if not attrs.get("username") and not attrs.get("share_code"):
            raise serializers.ValidationError("username or share_code is required.")
        return attrs


class ShareToggleSerializer(serializers.Serializer):
    share_location = serializers.BooleanField()


class FriendLocationSerializer(serializers.Serializer):
    username = serializers.CharField()
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()
    recorded_at = serializers.DateTimeField()


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "notification_type", "payload", "created_at", "read_at"]
        read_only_fields = fields
