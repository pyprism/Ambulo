from django.conf import settings
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)

from utils.audit import record_audit_event
from utils.permissions import IsStaffUser

from .models import AuditLog, Device, RegistrationClosed, User
from .serializers import (
    AuditLogSerializer,
    ChangePasswordSerializer,
    DeviceSerializer,
    UserRegisterSerializer,
    UserSerializer,
    UserSettingsSerializer,
)


def _revoke_all_refresh_tokens(user):
    """Blacklist every outstanding refresh token for user.

    Note: this stops future token *refreshes* immediately; an already-issued
    access token stays valid until its own expiry (SIMPLE_JWT
    ACCESS_TOKEN_LIFETIME) since SimpleJWT's blacklist only gates refresh —
    not a full instant revoke, but bounds the compromise window to that TTL.
    """
    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)


class UserViewSet(
    mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet
):
    """Self-service accounts.

    Non-staff users only ever see themselves; staff (the first-registered
    admin) can list/inspect all accounts.
    """

    def get_queryset(self):
        user = self.request.user
        if user.is_authenticated and user.is_staff:
            return User.objects.all()
        return User.objects.filter(pk=user.pk)

    def get_serializer_class(self):
        if self.action == "register":
            return UserRegisterSerializer
        if self.action == "change_password":
            return ChangePasswordSerializer
        return UserSerializer

    def get_permissions(self):
        if self.action == "register":
            return [AllowAny()]
        return super().get_permissions()

    @action(detail=False, methods=["post"], permission_classes=[AllowAny])
    def register(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = User.objects.create_registered_user(
                **serializer.validated_data,
                registration_open=settings.REGISTRATION_OPEN,
            )
        except RegistrationClosed:
            return Response(
                {"message": "Registration is closed on this server."},
                status=status.HTTP_403_FORBIDDEN,
            )
        record_audit_event(request, "user.register", username=user.username)
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get", "patch"])
    def me(self, request):
        if request.method == "PATCH":
            serializer = UserSettingsSerializer(
                request.user, data=request.data, partial=True
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
        return Response(UserSerializer(request.user).data)

    @action(detail=False, methods=["post"])
    def change_password(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        if not user.check_password(serializer.validated_data["old_password"]):
            return Response(
                {"message": "Old password is incorrect."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user.set_password(serializer.validated_data["new_password"])
        user.must_change_password = False
        user.save(update_fields=["password", "must_change_password"])
        _revoke_all_refresh_tokens(user)
        record_audit_event(request, "user.change_password")
        return Response(status=status.HTTP_204_NO_CONTENT)


class DeviceViewSet(viewsets.ModelViewSet):
    serializer_class = DeviceSerializer

    def get_queryset(self):
        return Device.objects.for_user(self.request.user)

    def create(self, request, *args, **kwargs):
        from utils.exceptions import CrossUserConflict

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            device = Device.objects.register_for_user(
                user=request.user,
                device_id=data["id"],
                name=data["name"],
                platform=data.get("platform", "other"),
            )
        except CrossUserConflict:
            return Response(
                {"message": "Device id belongs to another user."},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(DeviceSerializer(device).data, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        serializer.save(user=self.request.user)


class AuditLogViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """Admin-only security event trail (admin
    'views service/job health', no automatic access to other users' data
    beyond this operational log)."""

    serializer_class = AuditLogSerializer
    permission_classes = [IsStaffUser]
    filterset_fields = ["action"]

    def get_queryset(self):
        return AuditLog.objects.select_related("user").all()
