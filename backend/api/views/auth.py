from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from oauth.services import verify_telegram_init_data

from ..permissions import is_staff
from ..serializers.users import MeSerializer

User = get_user_model()


class StaffTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Phone + password login. Only staff may get a token — the admin has the same rule."""

    default_error_messages = {
        **TokenObtainPairSerializer.default_error_messages,
        "no_active_account": "Телефон ёки парол нотўғри.",
    }

    def validate(self, attrs):
        data = super().validate(attrs)
        if not is_staff(self.user):
            raise serializers.ValidationError({"detail": "Нет доступа к панели."})
        data["user"] = MeSerializer(self.user).data
        return data


class LoginView(TokenObtainPairView):
    serializer_class = StaffTokenObtainPairSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"


class LogoutView(APIView):
    """Blacklist the refresh token so it can't mint new access tokens."""

    def post(self, request):
        try:
            RefreshToken(request.data.get("refresh", "")).blacklist()
        except TokenError:
            pass  # already invalid — logging out is still a success
        return Response(status=status.HTTP_204_NO_CONTENT)


def _tokens_for(user):
    refresh = RefreshToken.for_user(user)
    return {"refresh": str(refresh), "access": str(refresh.access_token)}


class TelegramLoginSerializer(serializers.Serializer):
    init_data = serializers.CharField()


class TelegramLoginView(APIView):
    """Log in from inside Telegram (WebApp). The initData signature is verified with the
    bot token, then the user is looked up by the telegram_id the bot linked on /start.

    Disabled unless TELEGRAM_WEBAPP_LOGIN_ENABLED: the signature proves who the Telegram
    user is, but the bot's /start currently links ANY user id without checking, so the
    telegram_id -> user mapping is not trustworthy yet (see core/settings.py).
    Superusers are never logged in this way."""

    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = TelegramLoginSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        if not settings.TELEGRAM_WEBAPP_LOGIN_ENABLED:
            return Response(
                {"detail": "Telegram орқали кириш ўчирилган."},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = TelegramLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tg_user = verify_telegram_init_data(
            serializer.validated_data["init_data"],
            settings.TELEGRAM_BOT_TOKEN,
            settings.TELEGRAM_INIT_DATA_MAX_AGE,
        )
        if tg_user is None:
            return Response(
                {"detail": "Telegram маълумотлари тасдиқланмади."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        users = list(User.objects.filter(telegram_id=tg_user["id"])[:2])
        # telegram_id isn't unique: two accounts sharing one is ambiguous, refuse.
        user = users[0] if len(users) == 1 else None
        if user is None or not is_staff(user) or user.is_superuser:
            return Response(
                {"detail": "Telegram профилингиз панелга уланмаган."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response({**_tokens_for(user), "user": MeSerializer(user).data})


class MeView(APIView):
    def get(self, request):
        return Response(MeSerializer(request.user).data)
