from rest_framework import serializers

COMMON_SYNC_FIELDS = [
    "id",
    "local_rev",
    "server_rev",
    "sync_state",
    "source",
    "created_at",
    "updated_at",
    "deleted_at",
    "base_server_rev",
]
COMMON_SYNC_READ_ONLY_FIELDS = ["server_rev", "created_at", "updated_at"]


class SyncableSerializer(serializers.ModelSerializer):
    """Base for every syncable record's serializer. Concrete serializers set
    ``Meta.fields = COMMON_SYNC_FIELDS + [...domain fields]`` and
    ``Meta.read_only_fields = COMMON_SYNC_READ_ONLY_FIELDS``.

    id is writable (client-generated pk) — ModelSerializer would otherwise
    mark the pk read-only.
    """

    id = serializers.UUIDField()
    base_server_rev = serializers.IntegerField(
        required=False, allow_null=True, write_only=True
    )
