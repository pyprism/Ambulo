import csv
import io
import json
import os
import tempfile
import uuid
from datetime import timedelta

from celery import shared_task
from django.core.files import File
from django.utils.dateparse import parse_datetime

from health.models import HealthSample
from tracking.models import LocationPoint

from .models import ExportJob, ImportJob
from utils.enums import ExportFormat, JobStatus
from .parsers import PARSERS

# Dedupe tolerance. Coord: ~5.5m.
# Timestamp: a window, not exact match — sub-second precision differs
# between parsers/re-exports of "the same" fix and would otherwise defeat
# dedupe on re-import.
COORD_DEDUPE_TOLERANCE = 0.00005
TIMESTAMP_DEDUPE_TOLERANCE = timedelta(seconds=1)


@shared_task(name="imports.preview_import")
def preview_import(job_id):
    """Dry-run parse pass: dedupe-checks and validates every record but
    writes nothing, so the client can inspect counts/errors before
    committing.
    Leaves the job in preview_ready; ImportJobViewSet.commit re-runs the
    same pass with commit=True to actually write."""
    job = ImportJob.objects.select_related("user").get(pk=job_id)
    job.status = JobStatus.processing
    job.save(update_fields=["status"])
    _run_import(job, commit=False)


@shared_task(name="imports.process_import")
def process_import(job_id):
    job = ImportJob.objects.select_related("user").get(pk=job_id)
    job.status = JobStatus.processing
    job.save(update_fields=["status"])
    _run_import(job, commit=True)


def _run_import(job, commit):
    parser = PARSERS.get(job.source_format)
    if parser is None:
        job.status = JobStatus.failed
        job.error_message = f"No parser for format '{job.source_format}'."
        job.save(update_fields=["status", "error_message"])
        return

    imported = skipped_duplicate = 0
    errors = []
    try:
        with job.file.open("rb") as fh:
            for record in parser(fh):
                try:
                    created = _import_record(job.user, record, commit, job)
                except Exception as exc:  # one bad row must not fail the whole job
                    errors.append(str(exc))
                    continue
                if created:
                    imported += 1
                else:
                    skipped_duplicate += 1
    except Exception as exc:
        job.status = JobStatus.failed
        job.error_message = str(exc)
        job.save(update_fields=["status", "error_message"])
        return

    job.summary = {
        "imported": imported,
        "skipped_duplicate": skipped_duplicate,
        "errors": errors[:50],
    }
    if not commit:
        job.status = JobStatus.preview_ready
    else:
        job.status = JobStatus.partial if errors else JobStatus.completed
    job.save(update_fields=["summary", "status"])


def _import_record(user, record, commit, job):
    kind = record.get("kind")
    if kind == "location_point":
        return _import_location_point(user, record, commit, job)
    if kind == "health_sample":
        return _import_health_sample(user, record, commit, job)
    raise ValueError(f"Unknown import record kind '{kind}'")


def _import_location_point(user, record, commit, job):
    if (
        record.get("latitude") is None
        or record.get("longitude") is None
        or not record.get("recorded_at")
    ):
        raise ValueError("Missing latitude/longitude/recorded_at")

    recorded_at = parse_datetime(record["recorded_at"])
    if recorded_at is None:
        raise ValueError(f"Unparseable recorded_at: {record['recorded_at']!r}")

    latitude = round(float(record["latitude"]), 6)
    longitude = round(float(record["longitude"]), 6)

    duplicate = (
        LocationPoint.objects.for_user(user)
        .filter(
            recorded_at__gte=recorded_at - TIMESTAMP_DEDUPE_TOLERANCE,
            recorded_at__lte=recorded_at + TIMESTAMP_DEDUPE_TOLERANCE,
            latitude__gte=latitude - COORD_DEDUPE_TOLERANCE,
            latitude__lte=latitude + COORD_DEDUPE_TOLERANCE,
            longitude__gte=longitude - COORD_DEDUPE_TOLERANCE,
            longitude__lte=longitude + COORD_DEDUPE_TOLERANCE,
        )
        .exists()
    )
    if duplicate:
        return False

    if commit:
        LocationPoint.objects.create(
            id=uuid.uuid4(),
            user=user,
            latitude=latitude,
            longitude=longitude,
            altitude=record.get("altitude"),
            battery_level=record.get("battery_level"),
            recorded_at=recorded_at,
            source="import",
            import_job=job,
        )
    return True


def _import_health_sample(user, record, commit, job):
    recorded_at = parse_datetime(record["recorded_at"])
    if recorded_at is None:
        raise ValueError(f"Unparseable recorded_at: {record['recorded_at']!r}")

    duplicate = (
        HealthSample.objects.for_user(user)
        .filter(
            metric_type=record["metric_type"],
            recorded_at__gte=recorded_at - TIMESTAMP_DEDUPE_TOLERANCE,
            recorded_at__lte=recorded_at + TIMESTAMP_DEDUPE_TOLERANCE,
        )
        .exists()
    )
    if duplicate:
        return False

    if commit:
        HealthSample.objects.create(
            id=uuid.uuid4(),
            user=user,
            metric_type=record["metric_type"],
            value=record["value"],
            recorded_at=recorded_at,
            source="import",
            import_job=job,
        )
    return True


@shared_task(name="imports.process_export")
def process_export(job_id):
    """Streams the archive to a temp file row-by-row instead of building the
    whole document in memory — a multi-year account (the load test used
    105k+ points) must not risk OOMing a worker on export. JSON is a full account archive across every syncable
    type, grouped by type; CSV/GPX/GeoJSON stay location-history-scoped."""
    job = ExportJob.objects.select_related("user").get(pk=job_id)
    job.status = JobStatus.processing
    job.save(update_fields=["status"])

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name
            filename = _stream_export(job.export_format, job.user, tmp)
        with open(tmp_path, "rb") as fh:
            job.file.save(filename, File(fh), save=False)
    except Exception as exc:
        job.status = JobStatus.failed
        job.error_message = str(exc)
        job.save(update_fields=["status", "error_message"])
        return
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

    job.status = JobStatus.completed
    job.save(update_fields=["file", "status"])


def _stream_export(export_format, user, fh):
    if export_format == ExportFormat.json:
        return _stream_full_account_json(user, fh)

    points = (
        LocationPoint.objects.for_user(user)
        .not_deleted()
        .order_by("recorded_at")
        .iterator(chunk_size=2000)
    )

    if export_format == ExportFormat.csv:
        text_fh = io.TextIOWrapper(fh, encoding="utf-8", newline="")
        writer = csv.writer(text_fh)
        writer.writerow(["id", "latitude", "longitude", "altitude", "recorded_at"])
        for p in points:
            writer.writerow(
                [
                    str(p.pk),
                    p.latitude,
                    p.longitude,
                    p.altitude,
                    p.recorded_at.isoformat(),
                ]
            )
        text_fh.flush()
        text_fh.detach()  # don't close the underlying binary temp file
        return "export.csv"

    if export_format == ExportFormat.gpx:
        fh.write(
            b'<?xml version="1.0" encoding="UTF-8"?>\n'
            b'<gpx version="1.1" creator="Ambulo">\n<trk><trkseg>\n'
        )
        for p in points:
            ele = f"<ele>{p.altitude}</ele>" if p.altitude is not None else ""
            fh.write(
                (
                    f'<trkpt lat="{p.latitude}" lon="{p.longitude}">{ele}'
                    f"<time>{p.recorded_at.isoformat()}</time></trkpt>\n"
                ).encode("utf-8")
            )
        fh.write(b"</trkseg></trk>\n</gpx>")
        return "export.gpx"

    if export_format == ExportFormat.geojson:
        fh.write(b'{"type":"FeatureCollection","features":[')
        for i, p in enumerate(points):
            feature = {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [p.longitude, p.latitude]},
                "properties": {
                    "recorded_at": p.recorded_at.isoformat(),
                    "altitude": p.altitude,
                },
            }
            fh.write((b"," if i else b"") + json.dumps(feature).encode("utf-8"))
        fh.write(b"]}")
        return "export.geojson"

    raise ValueError(f"Unknown export format '{export_format}'")


def _stream_full_account_json(user, fh):
    """Every syncable type , grouped by type
    name, plus DailyRollup (deliberately excluded from sync.registry so it
    can't be spoofed via /sync/upload — that only gates the write path, not
    this read-only export) and the user's friendships."""
    from sync.registry import all_syncable_types, get_syncable
    from health.models import DailyRollup
    from health.serializers import DailyRollupSerializer
    from social.models import Friendship

    fh.write(b"{")
    for type_name in all_syncable_types():
        model, serializer_class = get_syncable(type_name)
        fh.write(json.dumps(type_name).encode("utf-8") + b":[")
        qs = (
            model.objects.for_user(user)
            .not_deleted()
            .order_by("server_rev")
            .iterator(chunk_size=2000)
        )
        for i, obj in enumerate(qs):
            fh.write(
                (b"," if i else b"")
                + json.dumps(serializer_class(obj).data, default=str).encode("utf-8")
            )
        fh.write(b"],")

    fh.write(b'"daily_rollup":[')
    rollups = (
        DailyRollup.objects.for_user(user).order_by("date").iterator(chunk_size=2000)
    )
    for i, rollup in enumerate(rollups):
        fh.write(
            (b"," if i else b"")
            + json.dumps(DailyRollupSerializer(rollup).data, default=str).encode(
                "utf-8"
            )
        )
    fh.write(b"],")

    fh.write(b'"friendships":[')
    friendships = (
        Friendship.objects.involving(user)
        .select_related("requester", "addressee")
        .iterator(chunk_size=500)
    )
    for i, friendship in enumerate(friendships):
        payload = {
            "id": str(friendship.pk),
            "requester": friendship.requester.username,
            "addressee": friendship.addressee.username,
            "status": friendship.status,
            "created_at": friendship.created_at.isoformat(),
        }
        fh.write((b"," if i else b"") + json.dumps(payload).encode("utf-8"))
    fh.write(b"]}")
    return "export.json"
