from rest_framework.routers import DefaultRouter

from .views import HealthzViewSet, SyncViewSet

router = DefaultRouter()
router.register("sync", SyncViewSet, basename="sync")
router.register("healthz", HealthzViewSet, basename="healthz")

urlpatterns = router.urls
