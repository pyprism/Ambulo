import uuid

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from accounts.models import Device, User


def _register_payload(username, email):
    return {
        "username": username,
        "email": email,
        "password": "V3ry-Long-Random-Passphrase-91",
    }


@pytest.fixture
def api_client():
    return APIClient()


@pytest.mark.django_db
def test_first_registered_user_becomes_admin_and_next_user_does_not(api_client):
    first = api_client.post(
        "/api/accounts/users/register/",
        _register_payload("alice", "alice@example.com"),
        format="json",
    )
    second = api_client.post(
        "/api/accounts/users/register/",
        _register_payload("bob", "bob@example.com"),
        format="json",
    )

    assert first.status_code == 201
    assert first.data["is_staff"] is True
    assert first.data["is_superuser"] is True
    assert second.status_code == 201
    assert second.data["is_staff"] is False
    assert second.data["is_superuser"] is False


@pytest.mark.django_db
def test_registered_user_email_is_stored_lowercase(api_client):
    response = api_client.post(
        "/api/accounts/users/register/",
        _register_payload("mixedcase", "User@Example.COM"),
        format="json",
    )

    assert response.status_code == 201
    user = User.objects.get(username="mixedcase")
    assert user.email == "user@example.com"
    assert response.data["email"] == "user@example.com"


@pytest.mark.django_db
@override_settings(REGISTRATION_OPEN=False)
def test_registration_closed_rejects_new_accounts(api_client):
    response = api_client.post(
        "/api/accounts/users/register/",
        _register_payload("closed", "closed@example.com"),
        format="json",
    )

    assert response.status_code == 403
    assert response.data["message"] == "Registration is closed on this server."
    assert User.objects.count() == 0


@pytest.mark.django_db
def test_device_id_collision_rejected_not_adopted():
    alice = User.objects.create_registered_user(
        username="alice", email="alice@example.com", password="testpass12345"
    )
    bob = User.objects.create_registered_user(
        username="bob", email="bob@example.com", password="testpass12345"
    )
    device_id = uuid.uuid4()
    alice_client = APIClient()
    alice_client.force_authenticate(user=alice)
    bob_client = APIClient()
    bob_client.force_authenticate(user=bob)

    alice_client.post(
        "/api/accounts/devices/",
        {"id": str(device_id), "name": "Alice phone", "platform": "ios"},
        format="json",
    )
    response = bob_client.post(
        "/api/accounts/devices/",
        {"id": str(device_id), "name": "Bob phone", "platform": "android"},
        format="json",
    )

    assert response.status_code == 409
    assert response.data["message"] == "Device id belongs to another user."
    device = Device.objects.get(pk=device_id)
    assert device.user == alice
    assert device.name == "Alice phone"
