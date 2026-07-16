from django.core.cache import cache
from django.db import connection
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from utils.enums import SyncState
from utils.etc import resolve_device
from utils.exceptions import CrossUserConflict
from utils.permissions import IsStaffUser

from .registry import all_syncable_types, get_syncable
from .tasks import ping
from accounts.models import AuditLog, Device, User
from health.models import HealthSample
from tracking.models import LocationPoint

DOWNLOAD_BATCH_LIMIT = 500


class SyncableModelViewSet(viewsets.ModelViewSet):
    """Batch, idempotent create + tombstone soft-delete for any SyncableModel
    Subclasses set ``model`` and ``serializer_class``.
    POST accepts a single object or a JSON array; every record is upserted
    on its client UUID via SyncableManager.upsert_for_user, so retries never
    duplicate and cross-user id collisions/conflicts come back as separate
    response buckets instead of a 500.
    """

    model = None

    def get_queryset(self):
        return self.model.objects.for_user(self.request.user).not_deleted()

    def create(self, request, *args, **kwargs):
        payload = request.data if isinstance(request.data, list) else [request.data]
        device = resolve_device(request)
        accepted, rejected, conflicts = [], [], []
        for raw in payload:
            # A list entry that isn't an object (e.g. a bare string/number)
            # would 500 on raw.get("id") below instead of a clean rejection
            if not isinstance(raw, dict):
                rejected.append(
                    {"id": None, "errors": "Each record must be an object."}
                )
                continue
            serializer = self.get_serializer(data=raw)
            if not serializer.is_valid():
                rejected.append({"id": raw.get("id"), "errors": serializer.errors})
                continue
            data = serializer.validated_data
            record_id = data.pop("id")
            base_server_rev = data.pop("base_server_rev", None)
            try:
                obj, _created, conflict = self.model.objects.upsert_for_user(
                    user=request.user,
                    record_id=record_id,
                    defaults=data,
                    device=device,
                    base_server_rev=base_server_rev,
                )
            except CrossUserConflict:
                rejected.append(
                    {
                        "id": str(record_id),
                        "errors": "Record id belongs to another user.",
                    }
                )
                continue
            (conflicts if conflict else accepted).append(self.get_serializer(obj).data)
        response_status = status.HTTP_201_CREATED if accepted else status.HTTP_200_OK
        return Response(
            {"accepted": accepted, "rejected": rejected, "conflicts": conflicts},
            status=response_status,
        )

    def perform_destroy(self, instance):
        instance.deleted_at = timezone.now()
        instance.sync_state = SyncState.deleted_pending_sync
        instance.save()


class SyncViewSet(viewsets.ViewSet):
    """Generic multi-record-type sync surface .

    upload: {"records": {"<type>": [ {...}, ... ], ...}}
    download: ?<type>=<cursor>&<type2>=<cursor2> -> next batch per type,
    including tombstones, each with its own next cursor + has_more flag.
    """

    def _accept_reject(self, request, model, serializer_class, raw_records, device):
        accepted, rejected, conflicts = [], [], []
        for raw in raw_records:
            if not isinstance(raw, dict):
                rejected.append(
                    {"id": None, "errors": "Each record must be an object."}
                )
                continue
            serializer = serializer_class(data=raw, context={"request": request})
            if not serializer.is_valid():
                rejected.append({"id": raw.get("id"), "errors": serializer.errors})
                continue
            data = serializer.validated_data
            record_id = data.pop("id")
            base_server_rev = data.pop("base_server_rev", None)
            try:
                obj, _created, conflict = model.objects.upsert_for_user(
                    user=request.user,
                    record_id=record_id,
                    defaults=data,
                    device=device,
                    base_server_rev=base_server_rev,
                )
            except CrossUserConflict:
                rejected.append(
                    {
                        "id": str(record_id),
                        "errors": "Record id belongs to another user.",
                    }
                )
                continue
            (conflicts if conflict else accepted).append(str(obj.pk))
        return accepted, rejected, conflicts

    @action(detail=False, methods=["post"])
    def upload(self, request):
        # request.data isn't guaranteed to be a dict (client could POST a
        # bare list/string/number), and "records"/each batch value isn't
        # guaranteed to have the shape we expect either — .items()/.get()
        # on the wrong type would 500 instead of a clean 400.
        if not isinstance(request.data, dict):
            return Response(
                {"message": "Request body must be a JSON object."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        batches = request.data.get("records") or {}
        if not isinstance(batches, dict):
            return Response(
                {"message": "'records' must be an object mapping type name to a list."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        device = resolve_device(request)
        results = {}
        for type_name, raw_records in batches.items():
            if not isinstance(raw_records, list):
                results[type_name] = {
                    "error": f"'{type_name}' must be a list of records."
                }
                continue
            entry = get_syncable(type_name)
            if entry is None:
                results[type_name] = {"error": f"Unknown syncable type '{type_name}'."}
                continue
            model, serializer_class = entry
            accepted, rejected, conflicts = self._accept_reject(
                request, model, serializer_class, raw_records, device
            )
            results[type_name] = {
                "accepted": accepted,
                "rejected": rejected,
                "conflicts": conflicts,
            }
        return Response(results, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"])
    def download(self, request):
        response = {}
        for type_name in all_syncable_types():
            model, serializer_class = get_syncable(type_name)
            raw_cursor = request.query_params.get(type_name, 0) or 0
            try:
                cursor = int(raw_cursor)
            except (TypeError, ValueError):
                return Response(
                    {"message": f"'{type_name}' cursor must be an integer."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            # Fetch one extra row to answer has_more without an off-by-one
            # on the exact-limit case.
            fetched = list(
                model.objects.for_user(request.user).changed_since(cursor)[
                    : DOWNLOAD_BATCH_LIMIT + 1
                ]
            )
            has_more = len(fetched) > DOWNLOAD_BATCH_LIMIT
            qs = fetched[:DOWNLOAD_BATCH_LIMIT]
            response[type_name] = {
                "records": serializer_class(qs, many=True).data,
                "cursor": qs[-1].server_rev if qs else cursor,
                "has_more": has_more,
            }
        return Response(response)


class HealthzViewSet(viewsets.ViewSet):
    """API / worker / queue / db health ."""

    permission_classes = [AllowAny]

    # Public, unauthenticated endpoint — the worker ping publishes a broker
    # message and blocks up to 2s. Cache that expensive part so repeated
    # hits (even many, even from one caller behind AnonRateThrottle) can't
    # turn it into a broker-flooding / worker-blocking lever.
    WORKER_CHECK_CACHE_KEY = "healthz:worker_checks"
    WORKER_CHECK_CACHE_TTL = 5

    def list(self, request):
        worker_checks = cache.get(self.WORKER_CHECK_CACHE_KEY)
        if worker_checks is None:
            worker_checks = {
                "worker": self._check_worker(),
                "queue_depth": self._queue_depth(),
            }
            cache.set(
                self.WORKER_CHECK_CACHE_KEY, worker_checks, self.WORKER_CHECK_CACHE_TTL
            )

        checks = {"database": self._check_database(), **worker_checks}
        healthy = (
            checks["database"]
            and checks["worker"]
            and checks["queue_depth"] is not None
        )
        return Response(
            {"status": "ok" if healthy else "degraded", "checks": checks},
            status=(
                status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE
            ),
        )

    def _check_database(self):
        try:
            connection.ensure_connection()
            return True
        except Exception:
            return False

    def _check_worker(self):
        try:
            ping.apply_async().get(timeout=2)
            return True
        except Exception:
            return False

    def _queue_depth(self):
        from django.conf import settings

        from hiren.celery import app as celery_app

        try:
            with celery_app.connection_or_acquire() as conn:
                channel = conn.channel()
                return channel.queue_declare(
                    queue=settings.CELERY_TASK_DEFAULT_QUEUE, passive=True
                ).message_count
        except Exception:
            return None

    @action(detail=False, methods=["get"], permission_classes=[IsStaffUser])
    def overview(self, request):
        """Admin-only detailed ops view: healthz plus dataset size and
        recent security events. Public /healthz stays minimal/unauthenticated on purpose;
        this is the richer surface the admin console should call."""

        base = self.list(request).data

        base["dataset"] = {
            "users": User.objects.count(),
            "devices": Device.objects.count(),
            "location_points": LocationPoint.objects.count(),
            "health_samples": HealthSample.objects.count(),
        }
        base["recent_audit_log"] = [
            {
                "action": entry.action,
                "username": entry.user.username if entry.user_id else None,
                "created_at": entry.created_at,
            }
            for entry in AuditLog.objects.order_by("-created_at")[:20]
        ]
        return Response(base)
