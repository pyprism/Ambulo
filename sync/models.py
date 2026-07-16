import uuid

from django.conf import settings
from django.db import models, transaction

from utils.enums import SyncSource, SyncState

from utils.exceptions import CrossUserConflict


def _field_unchanged(existing, field, value):
    """Compare without triggering a relation fetch for FK fields."""
    if field in ("user", "device", "import_job"):
        return getattr(existing, f"{field}_id") == (
            value.pk if value is not None else None
        )
    return getattr(existing, field) == value


class SyncableQuerySet(models.QuerySet):
    def for_user(self, user):
        return self.filter(user=user)

    def not_deleted(self):
        return self.filter(deleted_at__isnull=True)

    def changed_since(self, server_rev):
        qs = self
        if server_rev:
            qs = qs.filter(server_rev__gt=server_rev)
        return qs.order_by("server_rev")


class RevisionCounter(models.Model):
    """One monotonic counter per concrete syncable model, used to assign
    server_rev. A shared sequence table avoids a raw-SQL migration (Postgres
    IDENTITY/serial) per new syncable model — every model just calls
    ``next(model_label)`` inside the caller's transaction."""

    model_label = models.CharField(max_length=100, unique=True)
    value = models.BigIntegerField(default=0)

    @classmethod
    def next(cls, model_label):
        counter, _ = cls.objects.select_for_update().get_or_create(
            model_label=model_label
        )
        counter.value = models.F("value") + 1
        counter.save(update_fields=["value"])
        counter.refresh_from_db(fields=["value"])
        return counter.value


class SyncableManager(models.Manager.from_queryset(SyncableQuerySet)):
    def upsert_for_user(
        self, user, record_id, defaults, device=None, base_server_rev=None
    ):
        """Idempotent create-or-update keyed on the client-supplied UUID pk.

        Locks the row for the duration of the check so two concurrent
        requests can't race a cross-user id collision into a silent
        ownership takeover .
        A colliding id owned by another user is rejected, never adopted.

        If the caller passes ``base_server_rev`` (the server_rev it last
        synced) and it no longer matches the row's current server_rev,
        someone else changed the record since — flag sync_state=conflict
        and leave server data untouched instead of blindly overwriting

        Returns (obj, created, conflict).
        """
        full_defaults = {**defaults, "user": user, "device": device}
        with transaction.atomic(using=self.db):
            existing = (
                self.model.objects.select_for_update().filter(pk=record_id).first()
            )
            if existing is not None and existing.user_id != user.pk:
                raise CrossUserConflict(record_id)
            if existing is not None:
                if (
                    base_server_rev is not None
                    and existing.server_rev != base_server_rev
                ):
                    existing.sync_state = SyncState.conflict
                    existing.save()
                    return existing, False, True
                target_sync_state = full_defaults.get("sync_state", SyncState.synced)
                # A retried/unmodified re-upload must not bump server_rev —
                # that would push the record back into every other device's
                # changed-since download for no reason.
                if existing.sync_state == target_sync_state and all(
                    _field_unchanged(existing, field, value)
                    for field, value in full_defaults.items()
                ):
                    return existing, False, False
                for field, value in full_defaults.items():
                    setattr(existing, field, value)
                existing.sync_state = target_sync_state
                existing.save()
                return existing, False, False
            obj = self.model(pk=record_id, **full_defaults)
            obj.save()
            return obj, True, False


class SyncableModel(models.Model):
    """Base for every syncable record.

    id is the stable client-generated UUID primary key. server_rev is a
    monotonic per-model counter (via RevisionCounter) assigned on every
    save, used as the changed-since cursor for downloads; local_rev is the
    client's own revision counter, carried through for conflict comparison.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s_set",
    )
    device = models.ForeignKey(
        "accounts.Device",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_set",
    )
    import_job = models.ForeignKey(
        "imports.ImportJob",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_set",
        help_text="Set when this record was created by an import — lets a "
        "user identify/revert one specific import batch.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    local_rev = models.PositiveIntegerField(default=0)
    server_rev = models.BigIntegerField(default=0, db_index=True, editable=False)
    sync_state = models.CharField(
        max_length=32, choices=SyncState.choices, default=SyncState.synced
    )
    source = models.CharField(
        max_length=16, choices=SyncSource.choices, default=SyncSource.manual
    )
    encrypted_blob = models.TextField(
        blank=True,
        default="",
        help_text=(
            "E2E-encryption groundwork. Reserved "
            "for an opaque client-encrypted payload the server stores "
            "without reading"
        ),
    )

    objects = SyncableManager()

    class Meta:
        abstract = True
        ordering = ("-server_rev",)
        get_latest_by = "server_rev"

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            # a partial save must still persist the bumped server_rev, or
            # the change becomes invisible to changed-since sync downloads
            kwargs["update_fields"] = set(update_fields) | {"server_rev"}
        with transaction.atomic(using=kwargs.get("using")):
            self.server_rev = RevisionCounter.next(self._meta.label)
            super().save(*args, **kwargs)
