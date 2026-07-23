from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import LocationPointViewSet, OwnTracksIngestView, PlaceViewSet, TripViewSet

router = DefaultRouter()
router.register("points", LocationPointViewSet, basename="location-point")
router.register("places", PlaceViewSet, basename="place")
router.register("trips", TripViewSet, basename="trip")

urlpatterns = [
    path("pub/", OwnTracksIngestView.as_view(), name="owntracks-pub")
] + router.urls
