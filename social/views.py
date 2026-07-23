from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from accounts.models import User
from tracking.models import LocationPoint
from utils.audit import record_audit_event
from utils.enums import FriendshipStatus, NotificationType

from .models import Friendship, Notification
from .serializers import (
    FriendLocationSerializer,
    FriendRequestSerializer,
    FriendshipSerializer,
    NotificationSerializer,
    ShareToggleSerializer,
)


def _resolve_target_user(data):
    username = data.get("username")
    share_code = data.get("share_code")
    if username:
        user = User.objects.filter(username__iexact=username).first()
    else:
        user = User.objects.filter(share_code=share_code).first()
    if user is None:
        # Do not turn friend requests into a username-existence oracle.
        raise ValueError("Unable to create friend request.")
    return user


class FriendshipViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Friend requests, accept/revoke/block, per-direction share toggle, and
    friends' latest-position query."""

    serializer_class = FriendshipSerializer

    def get_queryset(self):
        return Friendship.objects.involving(self.request.user).select_related(
            "requester", "addressee"
        )

    def get_serializer_class(self):
        if self.action == "request":
            return FriendRequestSerializer
        if self.action == "share":
            return ShareToggleSerializer
        if self.action == "locations":
            return FriendLocationSerializer
        return FriendshipSerializer

    @action(detail=False, methods=["post"])
    def request(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            target = _resolve_target_user(serializer.validated_data)
            friendship, created = Friendship.objects.send_request(request.user, target)
        except ValueError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except PermissionError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        if created:
            Notification.objects.create(
                user=target,
                notification_type=NotificationType.friend_request,
                payload={"from_username": request.user.username},
            )
        record_audit_event(request, "friend.request", target=target.username)
        response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(FriendshipSerializer(friendship).data, status=response_status)

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        friendship = self.get_object()
        if friendship.addressee_id != request.user.pk:
            raise PermissionDenied("Only the addressee can accept a friend request.")
        # Without this, an already-blocked (or already-accepted) row could be
        # re-accepted regardless of state — blocking wasn't actually durable
        # without an explicit pending-state check.
        if friendship.status != FriendshipStatus.pending:
            return Response(
                {
                    "message": f"Cannot accept a friendship in '{friendship.status}' state."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        friendship.status = FriendshipStatus.accepted
        friendship.responded_at = timezone.now()
        friendship.save()
        Notification.objects.create(
            user=friendship.requester,
            notification_type=NotificationType.friend_accept,
            payload={"from_username": request.user.username},
        )
        record_audit_event(request, "friend.accept", friendship_id=str(friendship.pk))
        return Response(FriendshipSerializer(friendship).data)

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        friendship = self.get_object()
        # A blocked relationship can only be lifted by whoever blocked it —
        # otherwise the blocked party deletes the row and immediately sends
        # a fresh request, bypassing the block entirely.
        if (
            friendship.status == FriendshipStatus.blocked
            and friendship.blocked_by_id != request.user.pk
        ):
            raise PermissionDenied(
                "Only the party who blocked this relationship can revoke it."
            )
        record_audit_event(request, "friend.revoke", friendship_id=str(friendship.pk))
        friendship.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def block(self, request, pk=None):
        friendship = self.get_object()
        friendship.status = FriendshipStatus.blocked
        friendship.blocked_by = request.user
        friendship.responded_at = timezone.now()
        friendship.save()
        record_audit_event(request, "friend.block", friendship_id=str(friendship.pk))
        return Response(FriendshipSerializer(friendship).data)

    @action(detail=True, methods=["patch"])
    def share(self, request, pk=None):
        friendship = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        share_value = serializer.validated_data["share_location"]
        if friendship.requester_id == request.user.pk:
            friendship.requester_shares_location = share_value
        else:
            friendship.addressee_shares_location = share_value
        friendship.save()
        return Response(FriendshipSerializer(friendship).data)

    @action(detail=False, methods=["get"])
    def locations(self, request):
        """Friends' latest positions, poll-based, respecting each friend's
        share toggle — never returns a point for a friend who has sharing
        off for this requester."""
        friends_by_id = {}
        for friendship in self.get_queryset().accepted():
            if not friendship.shares_with(request.user):
                continue
            friend = friendship.other(request.user)
            friends_by_id[friend.id] = friend

        latest_points = (
            LocationPoint.objects.filter(user_id__in=friends_by_id)
            .not_deleted()
            .order_by("user_id", "-recorded_at")
            .distinct("user_id")
        )
        results = []
        for point in latest_points:
            friend = friends_by_id[point.user_id]
            results.append(
                {
                    "username": friend.username,
                    "latitude": point.latitude,
                    "longitude": point.longitude,
                    "recorded_at": point.recorded_at,
                }
            )
        serializer = self.get_serializer(results, many=True)
        return Response(serializer.data)


class NotificationViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    serializer_class = NotificationSerializer

    def get_queryset(self):
        return Notification.objects.for_user(self.request.user)

    @action(detail=True, methods=["post"])
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        notification.read_at = timezone.now()
        notification.save(update_fields=["read_at"])
        return Response(NotificationSerializer(notification).data)
