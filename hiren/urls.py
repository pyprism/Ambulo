"""
URL configuration for hiren project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
"""

from django.urls import path, re_path, include
from django.conf import settings
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework_simplejwt.views import (
    TokenBlacklistView,
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)

urls = [
    path("api/token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/token/blacklist/", TokenBlacklistView.as_view(), name="token_blacklist"),
    path("api/token/verify/", TokenVerifyView.as_view(), name="token_verify"),
    path(
        "api-auth/", include("rest_framework.urls")
    ),  # For DRF's browsable API login/logout
    path("api/", include("accounts.urls")),
    path("api/", include("sync.urls")),
    path("api/", include("tracking.urls")),
    path("api/", include("health.urls")),
    path("api/", include("imports.urls")),
    path("api/", include("social.urls")),
]

if settings.DEBUG:
    from django.conf.urls.static import static

    debug_urls = [
        path("api/schema/", SpectacularAPIView.as_view(), name="openapi-schema"),
        path(
            "api/docs/",
            SpectacularSwaggerView.as_view(url_name="openapi-schema"),
            name="swagger-ui",
        ),
    ]
    if not settings.RUNNING_TESTS:
        import debug_toolbar

        debug_urls.append(re_path(r"^__debug__/", include(debug_toolbar.urls)))
    urlpatterns = (
        debug_urls
        + urls
        + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    )
else:
    urlpatterns = urls
