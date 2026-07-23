import secrets
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.db import connection, models, transaction

from utils.enums import BiologicalSex, DevicePlatform
from utils.exceptions import CrossUserConflict

# Arbitrary constant: pg_advisory_xact_lock key. Any int64 works,
# it just needs to be a value no other code path locks on.
FIRST_REGISTRATION_LOCK_KEY = 918_273_645  # fact: The sequence 918273645 is a famous mathematical pattern formed by the first five multiples of 9 written consecutively: 9, 18, 27, 36, and 45


def generate_share_code():
    return secrets.token_hex(4)


class UserManager(DjangoUserManager):
    def create_registered_user(self, *, username, email, password, **extra_fields):
        """Create a self-service-registered account.

        The first successful registration on the instance becomes
        admin/superuser. The advisory lock serializes
        concurrent registrations racing the "table empty" check — without
        it, two simultaneous first registrations could both become
        superuser.
        """
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(%s)", [FIRST_REGISTRATION_LOCK_KEY]
                )
            is_first_user = not self.exists()
            user = self.create_user(
                username=username, email=email, password=password, **extra_fields
            )
            if is_first_user:
                user.is_staff = True
                user.is_superuser = True
                user.save(update_fields=["is_staff", "is_superuser"])
        return user


class User(AbstractUser):
    email = models.EmailField(unique=True)
    must_change_password = models.BooleanField(default=False)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    share_code = models.CharField(max_length=16, unique=True, blank=True)
    location_retention_days = models.PositiveIntegerField(null=True, blank=True)
    # Weight/height are NOT here — they're time-varying readings, tracked as
    # HealthSample(metric_type=weight/height) like any other health metric
    # so they get a history graph for free. Only the profile attributes
    # that don't already fit that shape (age, sex — needed for the BMR
    # calorie estimate) live on the account.
    date_of_birth = models.DateField(null=True, blank=True)
    biological_sex = models.CharField(
        max_length=16, choices=BiologicalSex.choices, blank=True
    )
    e2e_encryption_enabled = models.BooleanField(
        default=False,
        help_text=("encrypts payloads before upload, and the server does nothing"),
    )

    objects = UserManager()

    REQUIRED_FIELDS = ["email"]

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.lower()
        if not self.share_code:
            self.share_code = generate_share_code()
        super().save(*args, **kwargs)


class DeviceQuerySet(models.QuerySet):
    def for_user(self, user):
        return self.filter(user=user)

    def active(self):
        return self.filter(is_active=True)


class DeviceManager(models.Manager.from_queryset(DeviceQuerySet)):
    def register_for_user(self, user, device_id, name, platform):
        """Idempotent per-account device registration.

        Pre-checks ownership like SyncableManager.upsert_for_user — a
        device_id already registered under another user must come back as a
        clean rejection, not an IntegrityError 500.
        """

        with transaction.atomic(using=self.db):
            existing = (
                self.model.objects.select_for_update().filter(pk=device_id).first()
            )
            if existing is not None and existing.user_id != user.pk:
                raise CrossUserConflict(device_id)
            device, _created = self.update_or_create(
                pk=device_id,
                user=user,
                defaults={"name": name, "platform": platform, "is_active": True},
            )
            return device


class Device(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="devices"
    )
    name = models.CharField(max_length=255)
    platform = models.CharField(
        max_length=16, choices=DevicePlatform.choices, default=DevicePlatform.other
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    objects = DeviceManager()

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.name} ({self.user_id})"


class AuditLogQuerySet(models.QuerySet):
    def for_user(self, user):
        return self.filter(user=user)


class AuditLog(models.Model):
    """Security-relevant event trail . user is
    nullable so a system/anonymous event (e.g. a failed registration
    attempt) can still be recorded."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=64)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AuditLogQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["action", "created_at"])]
