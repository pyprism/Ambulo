from rest_framework.routers import DefaultRouter

from .views import AuditLogViewSet, DeviceViewSet, UserViewSet

router = DefaultRouter()
router.register("accounts/users", UserViewSet, basename="user")
router.register("accounts/devices", DeviceViewSet, basename="device")
router.register("accounts/audit-log", AuditLogViewSet, basename="audit-log")

urlpatterns = router.urls
