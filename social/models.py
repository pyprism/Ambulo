import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from utils.enums import FriendshipStatus, NotificationType


class FriendshipQuerySet(models.QuerySet):
    def involving(self, user):
        return self.filter(Q(requester=user) | Q(addressee=user))

    def accepted(self):
        return self.filter(status=FriendshipStatus.accepted)

    def for_pair(self, user_a, user_b):
        return self.filter(
            Q(requester=user_a, addressee=user_b)
            | Q(requester=user_b, addressee=user_a)
        )


class FriendshipManager(models.Manager.from_queryset(FriendshipQuerySet)):
    def send_request(self, requester, addressee):
        if requester.pk == addressee.pk:
            raise ValueError("Cannot send a friend request to yourself.")
        existing = self.for_pair(requester, addressee).first()
        if existing is not None:
            if existing.status == FriendshipStatus.blocked:
                raise PermissionError("This relationship is blocked.")
            return existing, False
        friendship = self.create(requester=requester, addressee=addressee)
        return friendship, True


class Friendship(models.Model):
    """Not a SyncableModel — a friendship spans two accounts, which breaks
    the single-owner assumption the sync spine (for_user/upsert_for_user)
    is built on. Plain server-mediated relational model instead."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="friendship_requests_sent",
    )
    addressee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="friendship_requests_received",
    )
    status = models.CharField(
        max_length=16,
        choices=FriendshipStatus.choices,
        default=FriendshipStatus.pending,
    )
    requester_shares_location = models.BooleanField(default=True)
    addressee_shares_location = models.BooleanField(default=True)
    blocked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text=(
            "Who blocked this relationship. Only this user may revoke a "
            "blocked friendship — otherwise the blocked party could delete "
            "the row and immediately re-request."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    objects = FriendshipManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["requester", "addressee"], name="unique_friend_pair"
            )
        ]

    def other(self, user):
        return self.addressee if self.requester_id == user.pk else self.requester

    def shares_with(self, viewer):
        """Does the *other* party in this friendship share location with viewer?"""
        return (
            self.addressee_shares_location
            if self.requester_id == viewer.pk
            else self.requester_shares_location
        )


class NotificationQuerySet(models.QuerySet):
    def for_user(self, user):
        return self.filter(user=user)

    def unread(self):
        return self.filter(read_at__isnull=True)


class Notification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    notification_type = models.CharField(
        max_length=32, choices=NotificationType.choices
    )
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    objects = NotificationQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
