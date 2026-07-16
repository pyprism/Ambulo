import pytest
from rest_framework.test import APIClient

from accounts.models import User


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
