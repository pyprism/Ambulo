from rest_framework.routers import DefaultRouter

from .views import ExportJobViewSet, ImportJobViewSet

router = DefaultRouter()
router.register("imports", ImportJobViewSet, basename="import-job")
router.register("exports", ExportJobViewSet, basename="export-job")

urlpatterns = router.urls
