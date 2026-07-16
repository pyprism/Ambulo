from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from sync.registry import all_syncable_types, get_syncable
from utils.audit import record_audit_event
from utils.enums import SyncState, JobStatus
from utils.tasks import safe_delay

from .models import ExportJob, ImportJob
from .serializers import ExportJobSerializer, ImportJobSerializer
from .tasks import process_export, process_import, preview_import


class ImportJobViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Raw-file upload + Celery parse .

    Upload only previews (parses, dedupe-checks, no writes) — call
    ``commit`` once the client has inspected the summary to actually write
    the records .
    """

    serializer_class = ImportJobSerializer
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        return ImportJob.objects.for_user(self.request.user)

    def perform_create(self, serializer):
        job = serializer.save(user=self.request.user)
        record_audit_event(
            self.request,
            "import.create",
            job_id=str(job.pk),
            source_format=job.source_format,
        )
        safe_delay(preview_import, str(job.pk))

    @action(detail=True, methods=["post"])
    def commit(self, request, pk=None):
        job = self.get_object()
        if job.status != JobStatus.preview_ready:
            return Response(
                {
                    "message": (
                        f"Job must be in 'preview_ready' state to commit "
                        f"(current: '{job.status}')."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        job.status = JobStatus.pending
        job.save(update_fields=["status"])
        record_audit_event(request, "import.commit", job_id=str(job.pk))
        safe_delay(process_import, str(job.pk))
        return Response(ImportJobSerializer(job).data)

    @action(detail=True, methods=["post"])
    def revert(self, request, pk=None):
        """Tombstone every record this import wrote, across every syncable
        type."""
        job = self.get_object()
        now = timezone.now()
        tombstoned = 0
        for type_name in all_syncable_types():
            model, _serializer_class = get_syncable(type_name)
            records = model.objects.filter(
                user=request.user, import_job=job, deleted_at__isnull=True
            )
            for record in records:
                record.deleted_at = now
                record.sync_state = SyncState.deleted_pending_sync
                record.save()
                tombstoned += 1
        record_audit_event(
            request, "import.revert", job_id=str(job.pk), tombstoned=tombstoned
        )
        return Response({"tombstoned": tombstoned})


class ExportJobViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = ExportJobSerializer

    def get_queryset(self):
        return ExportJob.objects.for_user(self.request.user)

    def perform_create(self, serializer):
        job = serializer.save(user=self.request.user)
        record_audit_event(
            self.request,
            "export.create",
            job_id=str(job.pk),
            export_format=job.export_format,
        )
        safe_delay(process_export, str(job.pk))
