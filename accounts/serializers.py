from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import AuditLog, Device, User


class UserRegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("Unable to register with these details.")
        return value

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("Unable to register with these details.")
        return value

    def validate(self, attrs):
        # AUTH_PASSWORD_VALIDATORS (common-password/numeric/similarity/
        # min-length) is configured in settings but Django only runs it
        # when explicitly called — create_user/set_password never do
        #  min_length=8 above was the only real check.
        temp_user = User(
            username=attrs.get("username", ""), email=attrs.get("email", "")
        )
        try:
            validate_password(attrs["password"], user=temp_user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)})
        return attrs


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "is_staff",
            "is_superuser",
            "must_change_password",
            "date_joined",
            "last_seen_at",
            "share_code",
            "location_retention_days",
            "date_of_birth",
            "biological_sex",
        ]
        read_only_fields = fields


class UserSettingsSerializer(serializers.ModelSerializer):
    """Self-service settings a user may PATCH on their own account."""

    class Meta:
        model = User
        fields = ["location_retention_days", "date_of_birth", "biological_sex"]


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)

    def validate(self, attrs):
        request = self.context.get("request")
        user = request.user if request is not None else None
        try:
            validate_password(attrs["new_password"], user=user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": list(exc.messages)})
        return attrs


class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        fields = ["id", "name", "platform", "is_active", "created_at", "last_seen_at"]
        read_only_fields = ["is_active", "created_at", "last_seen_at"]

    def get_fields(self):
        # id is the client-generated pk — writable on create (the custom
        # DeviceViewSet.create reads it directly), but must never change on
        # an existing row: PATCHing a different id risks an undefined pk
        # rewrite on save() instead of a clean no-op.
        fields = super().get_fields()
        fields["id"] = serializers.UUIDField(read_only=self.instance is not None)
        return fields


class AuditLogSerializer(serializers.ModelSerializer):
    username = serializers.CharField(
        source="user.username", read_only=True, default=None
    )

    class Meta:
        model = AuditLog
        fields = ["id", "username", "action", "metadata", "ip_address", "created_at"]
        read_only_fields = fields
