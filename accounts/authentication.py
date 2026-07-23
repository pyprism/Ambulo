from rest_framework.throttling import SimpleRateThrottle
from rest_framework.exceptions import APIException
from rest_framework_simplejwt.views import TokenObtainPairView

from utils.audit import record_audit_event


class LoginThrottle(SimpleRateThrottle):
    """Rate-limit a credential target as well as the source address."""

    scope = "login"

    def get_cache_key(self, request, view):
        username = str(request.data.get("username", "")).strip().lower()
        return self.cache_format % {
            "scope": self.scope,
            "ident": f"{self.get_ident(request)}:{username}",
        }


class AuditedTokenObtainPairView(TokenObtainPairView):
    throttle_classes = [LoginThrottle]

    def post(self, request, *args, **kwargs):
        try:
            return super().post(request, *args, **kwargs)
        except APIException:
            record_audit_event(
                request,
                "user.login_failed",
                username=str(request.data.get("username", ""))[:150],
            )
            raise
