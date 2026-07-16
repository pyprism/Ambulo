from rest_framework.routers import DefaultRouter

from .views import FriendshipViewSet, NotificationViewSet

router = DefaultRouter()
router.register("friends", FriendshipViewSet, basename="friendship")
router.register("notifications", NotificationViewSet, basename="notification")

urlpatterns = router.urls
