import uuid

import pytest
from rest_framework.test import APIClient

from accounts.models import User
from sync.views import SyncableModelViewSet
from tracking.models import LocationPoint
from tracking.views import LocationPointViewSet
from utils.enums import SyncState


@pytest.fixture
def user(db):
    return User.objects.create_registered_user(
        username="alice", email="alice@example.com", password="testpass12345"
    )


@pytest.fixture
def other_user(db):
    return User.objects.create_registered_user(
        username="bob", email="bob@example.com", password="testpass12345"
    )


@pytest.fixture
def api_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def other_api_client(other_user):
    client = APIClient()
    client.force_authenticate(user=other_user)
    return client


def _point_payload(point_id=None, **overrides):
    payload = {
        "id": str(point_id or uuid.uuid4()),
        "latitude": 23.8,
        "longitude": 90.4,
        "recorded_at": "2026-07-15T12:00:00Z",
    }
    payload.update(overrides)
    return payload


@pytest.mark.django_db
def test_idempotent_repost_does_not_duplicate(api_client):
    point_id = uuid.uuid4()
    payload = [_point_payload(point_id)]

    api_client.post("/api/points/", payload, format="json")
    api_client.post("/api/points/", payload, format="json")

    assert LocationPoint.objects.filter(pk=point_id).count() == 1
    # An unchanged re-upload is a no-op — it must not bump server_rev, or
    # every retry would push the record back into every other device's
    # changed-since download for nothing.
    assert LocationPoint.objects.get(pk=point_id).server_rev == 1


@pytest.mark.django_db
def test_repost_with_changed_field_does_bump_server_rev(api_client):
    point_id = uuid.uuid4()
    api_client.post("/api/points/", [_point_payload(point_id)], format="json")
    api_client.post(
        "/api/points/", [_point_payload(point_id, latitude=24.0)], format="json"
    )

    point = LocationPoint.objects.get(pk=point_id)
    assert point.server_rev == 2
    assert point.latitude == 24.0


@pytest.mark.django_db
def test_cross_user_id_collision_is_rejected_not_adopted(api_client, other_api_client):
    point_id = uuid.uuid4()
    api_client.post("/api/points/", [_point_payload(point_id)], format="json")

    response = other_api_client.post(
        "/api/points/",
        [_point_payload(point_id, latitude=1.0, longitude=1.0)],
        format="json",
    )

    assert response.data["rejected"]
    assert not response.data["accepted"]
    point = LocationPoint.objects.get(pk=point_id)
    assert point.user.username == "alice"
    assert point.latitude == 23.8


@pytest.mark.django_db
def test_stale_base_server_rev_flags_conflict_without_overwriting(api_client):
    point_id = uuid.uuid4()
    api_client.post("/api/points/", [_point_payload(point_id)], format="json")

    response = api_client.post(
        "/api/points/",
        [_point_payload(point_id, latitude=45.0, longitude=45.0, base_server_rev=0)],
        format="json",
    )

    assert response.data["conflicts"]
    assert not response.data["accepted"]
    point = LocationPoint.objects.get(pk=point_id)
    assert point.latitude == 23.8
    assert point.sync_state == "conflict"


@pytest.mark.django_db
def test_tombstone_excluded_from_list_but_present_in_changed_since_download(api_client):
    point_id = uuid.uuid4()
    api_client.post("/api/points/", [_point_payload(point_id)], format="json")
    api_client.delete(f"/api/points/{point_id}/")

    list_response = api_client.get("/api/points/")
    assert all(row["id"] != str(point_id) for row in list_response.data["results"])

    download_response = api_client.get("/api/sync/download/?location_point=0")
    ids = [row["id"] for row in download_response.data["location_point"]["records"]]
    assert str(point_id) in ids


def test_syncable_model_viewset_is_exported_from_sync_views():
    assert issubclass(LocationPointViewSet, SyncableModelViewSet)


@pytest.mark.django_db
def test_syncable_viewset_accepts_single_object_payload(api_client, user):
    point_id = uuid.uuid4()

    response = api_client.post(
        "/api/points/",
        _point_payload(point_id),
        format="json",
    )

    assert response.status_code == 201
    assert response.data["accepted"][0]["id"] == str(point_id)
    assert not response.data["rejected"]
    point = LocationPoint.objects.get(pk=point_id)
    assert point.user == user
    assert point.server_rev == 1


@pytest.mark.django_db
def test_syncable_viewset_rejects_non_object_list_entries(api_client):
    response = api_client.post(
        "/api/points/",
        ["not-a-record", _point_payload()],
        format="json",
    )

    assert response.status_code == 201
    assert response.data["accepted"]
    assert response.data["rejected"] == [
        {"id": None, "errors": "Each record must be an object."}
    ]
    assert LocationPoint.objects.count() == 1


@pytest.mark.django_db
def test_syncable_viewset_destroy_creates_tombstone(api_client):
    point_id = uuid.uuid4()
    api_client.post("/api/points/", _point_payload(point_id), format="json")

    response = api_client.delete(f"/api/points/{point_id}/")

    assert response.status_code == 204
    point = LocationPoint.objects.get(pk=point_id)
    assert point.deleted_at is not None
    assert point.sync_state == SyncState.deleted_pending_sync
