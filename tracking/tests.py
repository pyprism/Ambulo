"""Pins the coordinate/domain-value validation added for"""

import uuid

import pytest
from rest_framework.test import APIClient

from accounts.models import User
from tracking.models import Place
from tracking.tasks import reverse_geocode_place


@pytest.fixture
def user(db):
    return User.objects.create_registered_user(
        username="alice", email="alice@example.com", password="testpass12345"
    )


@pytest.fixture
def api_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_out_of_range_latitude_rejected(api_client):
    response = api_client.post(
        "/api/points/",
        [
            {
                "id": str(uuid.uuid4()),
                "latitude": 999,
                "longitude": 50,
                "recorded_at": "2026-07-15T12:00:00Z",
            }
        ],
        format="json",
    )

    assert response.data["rejected"]
    assert not response.data["accepted"]


@pytest.mark.django_db
def test_negative_geofence_radius_rejected(api_client):
    response = api_client.post(
        "/api/places/",
        [
            {
                "id": str(uuid.uuid4()),
                "name": "Bad Place",
                "latitude": 10,
                "longitude": 10,
                "radius_meters": -5,
            }
        ],
        format="json",
    )

    assert response.data["rejected"]
    assert not response.data["accepted"]


@pytest.mark.django_db
def test_valid_point_still_accepted(api_client):
    response = api_client.post(
        "/api/points/",
        [
            {
                "id": str(uuid.uuid4()),
                "latitude": 23.8,
                "longitude": 90.4,
                "recorded_at": "2026-07-15T12:00:00Z",
            }
        ],
        format="json",
    )

    assert response.data["accepted"]
    assert not response.data["rejected"]


@pytest.mark.django_db
def test_reverse_geocode_updates_address_without_overwriting_stale_place_fields(
    user, monkeypatch
):
    place = Place.objects.create(
        user=user,
        name="Old name",
        latitude=23.8,
        longitude=90.4,
        radius_meters=100,
    )

    def update_name_while_task_has_stale_instance(_key):
        Place.objects.filter(pk=place.pk).update(name="Updated name")
        return "Geocoded address"

    monkeypatch.setattr(
        "tracking.tasks.cache.get", update_name_while_task_has_stale_instance
    )

    assert reverse_geocode_place(place.pk) == "Geocoded address"

    place.refresh_from_db()
    assert place.address == "Geocoded address"
    assert place.name == "Updated name"
