import io

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from imports.models import ImportJob
from imports.parsers import parse_gpx, parse_owntracks_csv, parse_tcx
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


def test_parse_gpx_skips_malformed_coordinates_and_continues():
    gpx = """<?xml version="1.0"?>
    <gpx>
      <trk><trkseg>
        <trkpt lat="not-a-number" lon="90.4">
          <time>2026-07-15T12:00:00Z</time>
        </trkpt>
        <trkpt lat="23.8" lon="90.4">
          <ele>9.5</ele>
          <time>2026-07-15T12:05:00Z</time>
        </trkpt>
      </trkseg></trk>
    </gpx>
    """

    records = list(parse_gpx(io.StringIO(gpx)))

    assert records == [
        {
            "kind": "location_point",
            "latitude": 23.8,
            "longitude": 90.4,
            "recorded_at": "2026-07-15T12:05:00Z",
            "altitude": 9.5,
        }
    ]


def test_parse_owntracks_csv_skips_malformed_numeric_rows_and_continues():
    csv_data = """time,lat,lon,alt,batt
1721044800,not-a-number,90.4,5,88
1721045100,23.8,90.4,6.5,87
"""

    records = list(parse_owntracks_csv(io.StringIO(csv_data)))

    assert records == [
        {
            "kind": "location_point",
            "latitude": 23.8,
            "longitude": 90.4,
            "recorded_at": "2024-07-15T12:05:00+00:00",
            "altitude": 6.5,
            "battery_level": 87.0,
        }
    ]


def test_parse_tcx_skips_malformed_numeric_trackpoints_and_continues():
    tcx = """<?xml version="1.0"?>
    <TrainingCenterDatabase>
      <Activities>
        <Activity>
          <Lap>
            <Track>
              <Trackpoint>
                <Time>2026-07-15T12:00:00Z</Time>
                <Position>
                  <LatitudeDegrees>not-a-number</LatitudeDegrees>
                  <LongitudeDegrees>90.4</LongitudeDegrees>
                </Position>
              </Trackpoint>
              <Trackpoint>
                <Time>2026-07-15T12:05:00Z</Time>
                <Position>
                  <LatitudeDegrees>23.8</LatitudeDegrees>
                  <LongitudeDegrees>90.4</LongitudeDegrees>
                </Position>
                <AltitudeMeters>8.5</AltitudeMeters>
              </Trackpoint>
            </Track>
          </Lap>
        </Activity>
      </Activities>
    </TrainingCenterDatabase>
    """

    records = list(parse_tcx(io.StringIO(tcx)))

    assert records == [
        {
            "kind": "location_point",
            "latitude": 23.8,
            "longitude": 90.4,
            "recorded_at": "2026-07-15T12:05:00Z",
            "altitude": 8.5,
        }
    ]
