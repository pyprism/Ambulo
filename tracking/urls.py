from rest_framework.routers import DefaultRouter

from .views import LocationPointViewSet, PlaceViewSet, TripViewSet

router = DefaultRouter()
router.register("points", LocationPointViewSet, basename="location-point")
router.register("places", PlaceViewSet, basename="place")
router.register("trips", TripViewSet, basename="trip")

urlpatterns = router.urls
