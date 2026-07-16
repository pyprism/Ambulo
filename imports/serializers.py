from rest_framework import serializers

from .models import ExportJob, ImportJob


class ImportJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = ImportJob
        fields = [
            "id",
            "source_format",
            "file",
            "status",
            "summary",
            "error_message",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "summary",
            "error_message",
            "created_at",
            "updated_at",
        ]


class ExportJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExportJob
        fields = [
            "id",
            "export_format",
            "status",
            "file",
            "error_message",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "file",
            "error_message",
            "created_at",
            "updated_at",
        ]
