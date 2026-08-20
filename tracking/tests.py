"""Pins the coordinate/domain-value validation added for"""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from tracking.models import LocationPoint, Place
from tracking.tasks import process_geofence_events, reverse_geocode_place


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


@pytest.mark.django_db
def test_geofence_sweep_on_never_processed_place_seeds_from_latest_point_only(
    user, monkeypatch
):
    """A Place with state_as_of=None (just created) has no natural lower
    bound on the sweep query — without one it replays every point the user
    has ever synced, holding a row lock, and can fire one friend
    notification per historical transition. It should instead seed from
    only the single most recent point."""
    notify_calls = []
    monkeypatch.setattr(
        "tracking.tasks._notify_friends",
        lambda *args, **kwargs: notify_calls.append(args),
    )

    place = Place.objects.create(
        user=user,
        name="Home",
        latitude=0,
        longitude=0,
        radius_meters=100,
        notify_friends=True,
    )
    now = timezone.now()
    # Replayed in full, this history alone would fire three transitions
    # (entered/exited/entered) before the latest point's exit.
    LocationPoint.objects.create(
        user=user, latitude=0, longitude=0, recorded_at=now - timedelta(days=5)
    )
    LocationPoint.objects.create(
        user=user, latitude=50, longitude=50, recorded_at=now - timedelta(days=4)
    )
    LocationPoint.objects.create(
        user=user, latitude=0, longitude=0, recorded_at=now - timedelta(days=3)
    )
    latest = LocationPoint.objects.create(
        user=user, latitude=50, longitude=50, recorded_at=now
    )

    process_geofence_events(user.pk)

    place.refresh_from_db()
    assert place.state_as_of == latest.recorded_at
    # currently_inside started False and the latest point is outside the
    # radius too, so seeding from it alone produces no transition at all —
    # proof the older entered/exited/entered history was never replayed.
    assert place.currently_inside is False
    assert notify_calls == []
