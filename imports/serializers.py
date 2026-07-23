from rest_framework import serializers

from .models import ExportJob, ImportJob


class ImportJobSerializer(serializers.ModelSerializer):
    source_file_available = serializers.BooleanField(source="file", read_only=True)

    class Meta:
        model = ImportJob
        fields = [
            "id",
            "source_format",
            "file",
            "source_file_available",
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
        extra_kwargs = {"file": {"write_only": True}}


class ExportJobSerializer(serializers.ModelSerializer):
    download_available = serializers.SerializerMethodField()

    def get_download_available(self, obj):
        return bool(obj.file)

    class Meta:
        model = ExportJob
        fields = [
            "id",
            "export_format",
            "status",
            "download_available",
            "error_message",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "error_message",
            "created_at",
            "updated_at",
        ]
