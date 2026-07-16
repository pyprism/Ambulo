from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from social.models import Friendship, Notification
from social.tasks import notify_friend_geofence_event
from tracking.models import LocationPoint
from utils.enums import FriendshipStatus, NotificationType


@pytest.fixture
def requester(db):
    return User.objects.create_registered_user(
        username="alice", email="alice@example.com", password="testpass12345"
    )


@pytest.fixture
def addressee(db):
    return User.objects.create_registered_user(
        username="bob", email="bob@example.com", password="testpass12345"
    )


@pytest.fixture
def requester_client(requester):
    client = APIClient()
    client.force_authenticate(user=requester)
    return client


@pytest.fixture
def addressee_client(addressee):
    client = APIClient()
    client.force_authenticate(user=addressee)
    return client


@pytest.mark.django_db
def test_accept_rejected_once_blocked(requester_client, addressee_client):
    friendship_id = requester_client.post(
        "/api/friends/request/", {"username": "bob"}, format="json"
    ).data["id"]
    requester_client.post(f"/api/friends/{friendship_id}/block/", format="json")

    response = addressee_client.post(
        f"/api/friends/{friendship_id}/accept/", format="json"
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_blocked_party_cannot_revoke_the_block(requester_client, addressee_client):
    friendship_id = requester_client.post(
        "/api/friends/request/", {"username": "bob"}, format="json"
    ).data["id"]
    requester_client.post(f"/api/friends/{friendship_id}/block/", format="json")

    response = addressee_client.post(
        f"/api/friends/{friendship_id}/revoke/", format="json"
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_blocker_can_revoke_their_own_block(requester_client, addressee_client):
    friendship_id = requester_client.post(
        "/api/friends/request/", {"username": "bob"}, format="json"
    ).data["id"]
    requester_client.post(f"/api/friends/{friendship_id}/block/", format="json")

    response = requester_client.post(
        f"/api/friends/{friendship_id}/revoke/", format="json"
    )

    assert response.status_code == 204


@pytest.mark.django_db
def test_blocked_party_cannot_re_request(requester_client, addressee_client):
    friendship_id = requester_client.post(
        "/api/friends/request/", {"username": "bob"}, format="json"
    ).data["id"]
    requester_client.post(f"/api/friends/{friendship_id}/block/", format="json")

    response = addressee_client.post(
        "/api/friends/request/", {"username": "alice"}, format="json"
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_friend_locations_fetch_latest_points_without_per_friend_queries(
    requester, requester_client, django_assert_num_queries
):
    now = timezone.now()
    friends = [
        User.objects.create_registered_user(
            username=f"friend-{index}",
            email=f"friend-{index}@example.com",
            password="testpass12345",
        )
        for index in range(3)
    ]
    for index, friend in enumerate(friends):
        Friendship.objects.create(
            requester=requester,
            addressee=friend,
            status=FriendshipStatus.accepted,
        )
        LocationPoint.objects.create(
            user=friend,
            latitude=10 + index,
            longitude=20 + index,
            recorded_at=now - timedelta(minutes=10),
        )
        LocationPoint.objects.create(
            user=friend,
            latitude=30 + index,
            longitude=40 + index,
            recorded_at=now,
        )

    with django_assert_num_queries(3):
        response = requester_client.get("/api/friends/locations/")

    assert response.status_code == 200
    locations = {row["username"]: row for row in response.data}
    assert set(locations) == {friend.username for friend in friends}
    for index, friend in enumerate(friends):
        assert locations[friend.username]["latitude"] == 30 + index
        assert locations[friend.username]["longitude"] == 40 + index


@pytest.mark.django_db
def test_geofence_notifications_created_in_bulk_for_share_enabled_friends(
    requester, addressee
):
    muted_friend = User.objects.create_registered_user(
        username="muted",
        email="muted@example.com",
        password="testpass12345",
    )
    Friendship.objects.create(
        requester=requester,
        addressee=addressee,
        status=FriendshipStatus.accepted,
    )
    Friendship.objects.create(
        requester=requester,
        addressee=muted_friend,
        status=FriendshipStatus.accepted,
        requester_shares_location=False,
    )

    count = notify_friend_geofence_event(str(requester.pk), "Home", "entered")

    assert count == 1
    notification = Notification.objects.get()
    assert notification.user == addressee
    assert notification.notification_type == NotificationType.friend_geofence
    assert notification.payload == {
        "friend_username": requester.username,
        "place": "Home",
        "event": "entered",
    }
