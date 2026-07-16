import uuid

from django.conf import settings
from django.db import models

from utils.enums import ImportFormat, ExportFormat, JobStatus


class JobQuerySet(models.QuerySet):
    def for_user(self, user):
        return self.filter(user=user)


class ImportJob(models.Model):
    """Async import job . Not a SyncableModel — it's a one-shot
    server-side job the client polls, not a multi-device-syncable record."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="import_jobs"
    )
    source_format = models.CharField(max_length=32, choices=ImportFormat.choices)
    file = models.FileField(upload_to="imports/%Y/%m/")
    status = models.CharField(
        max_length=16, choices=JobStatus.choices, default=JobStatus.pending
    )
    summary = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = JobQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)


class ExportJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="export_jobs"
    )
    export_format = models.CharField(max_length=16, choices=ExportFormat.choices)
    status = models.CharField(
        max_length=16, choices=JobStatus.choices, default=JobStatus.pending
    )
    file = models.FileField(upload_to="exports/%Y/%m/", blank=True, null=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = JobQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
