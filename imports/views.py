from django.http import FileResponse, Http404
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from utils.audit import record_audit_event
from utils.enums import JobStatus
from utils.tasks import safe_delay

from .models import ExportJob, ImportJob
from .serializers import ExportJobSerializer, ImportJobSerializer
from .tasks import process_export, process_import, preview_import, revert_import


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
        """Queue tombstoning so large imports never hold the HTTP request."""
        job = self.get_object()
        safe_delay(revert_import, str(job.pk))
        record_audit_event(request, "import.revert", job_id=str(job.pk), queued=True)
        return Response({"status": "queued"}, status=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        """Source files are only ever streamed to their owning user."""
        job = self.get_object()
        if not job.file:
            raise Http404
        return FileResponse(
            job.file.open("rb"),
            as_attachment=True,
            filename=job.file.name.rsplit("/", 1)[-1],
        )


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

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        """Export archives are private; do not expose MEDIA_ROOT URLs."""
        job = self.get_object()
        if not job.file:
            raise Http404
        return FileResponse(
            job.file.open("rb"),
            as_attachment=True,
            filename=job.file.name.rsplit("/", 1)[-1],
        )
