import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from imports.models import ImportJob
from tracking.models import LocationPoint
from utils.enums import ImportFormat, JobStatus, SyncState


@pytest.fixture
def user(db):
    return User.objects.create_registered_user(
        username="importer", email="importer@example.com", password="testpass12345"
    )


@pytest.fixture
def api_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _import_job(user, status=JobStatus.pending):
    return ImportJob.objects.create(
        user=user,
        source_format=ImportFormat.ambulo_json,
        file="imports/test.json",
        status=status,
    )


@pytest.mark.django_db
def test_import_commit_requires_preview_ready(api_client, user):
    job = _import_job(user, status=JobStatus.pending)

    response = api_client.post(f"/api/imports/{job.pk}/commit/", format="json")

    assert response.status_code == 400
    assert "preview_ready" in response.data["message"]
    job.refresh_from_db()
    assert job.status == JobStatus.pending


@pytest.mark.django_db
def test_import_commit_marks_pending_and_dispatches_task(api_client, user, monkeypatch):
    dispatched = []
    job = _import_job(user, status=JobStatus.preview_ready)

    def fake_safe_delay(task, *args, **kwargs):
        dispatched.append((task.name, args, kwargs))

    monkeypatch.setattr("imports.views.safe_delay", fake_safe_delay)

    response = api_client.post(f"/api/imports/{job.pk}/commit/", format="json")

    assert response.status_code == 200
    assert response.data["status"] == JobStatus.pending
    assert dispatched == [("imports.process_import", (str(job.pk),), {})]


@pytest.mark.django_db
def test_import_revert_tombstones_records_written_by_job(api_client, user):
    job = _import_job(user, status=JobStatus.completed)
    point = LocationPoint.objects.create(
        user=user,
        import_job=job,
        latitude=23.8,
        longitude=90.4,
        recorded_at=timezone.now(),
    )

    response = api_client.post(f"/api/imports/{job.pk}/revert/", format="json")

    assert response.status_code == 200
    assert response.data["tombstoned"] == 1
    point.refresh_from_db()
    assert point.deleted_at is not None
    assert point.sync_state == SyncState.deleted_pending_sync
