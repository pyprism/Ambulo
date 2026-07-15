"""
URL configuration for hiren project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
"""

from django.urls import path, re_path, include
from django.conf import settings
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
]

if settings.DEBUG:
    import debug_toolbar
    from rest_framework.permissions import AllowAny
    from rest_framework.schemas import get_schema_view

    debug_urls = [
        re_path(r"^__debug__/", include(debug_toolbar.urls)),
        path(
            "api/schema/",
            get_schema_view(
                title="Ambulo API",
                version="1.0.0",
                public=True,
                authentication_classes=[],
                permission_classes=[AllowAny],
            ),
            name="openapi-schema",
        ),
        # path("api/docs/", swagger_ui, name="swagger-ui"),
    ]
    urlpatterns = debug_urls + urls
else:
    urlpatterns = urls
