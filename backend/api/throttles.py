from rest_framework.throttling import SimpleRateThrottle


class LoginRateThrottle(SimpleRateThrottle):
    """Login throttle (rate: REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["login"]) keyed on
    the client IP that the "front" nginx puts in X-Real-IP (taken from the server
    nginx's X-Real-IP / X-Forwarded-For). Without it every request would look like it
    came from the front container — one shared bucket, so one person's typos would
    lock everyone out."""

    scope = "login"

    def get_ident(self, request):
        real_ip = request.META.get("HTTP_X_REAL_IP", "").strip()
        return real_ip or super().get_ident(request)

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}
