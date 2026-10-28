"""Base of the internal bot API views.

Authentication is the HMAC signature (api/authentication.py); the acting Telegram user
comes from the signed `X-Bot-Actor` header and is `request.auth`. Every role rule is
enforced here / in the services - the bot is trusted to relay, not to decide.
"""

import logging
from functools import cached_property

from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounting import services as S
from api.authentication import BotSignatureAuthentication
from api.permissions import IsBot
from core.exceptions import ServiceConflict, ServiceForbidden
from hr import services as HR
from oauth.models import TelegramMember

log = logging.getLogger("api.bot")


@extend_schema(exclude=True)
class BotAPIView(APIView):
    authentication_classes = [BotSignatureAuthentication]
    permission_classes = [IsBot]
    throttle_classes = []
    parser_classes = [JSONParser, MultiPartParser]
    pagination_class = None

    def handle_exception(self, exc):
        # 409 / 403 for "already done" / "your role may not"; any other ServiceError
        # stays a 400 (api/exceptions.py).
        if isinstance(exc, ServiceConflict):
            return Response({"detail": exc.message}, status=409)
        if isinstance(exc, ServiceForbidden):
            return Response({"detail": exc.message}, status=403)
        if isinstance(exc, (ValueError, TypeError, ArithmeticError)):
            # malformed input the views didn't validate: a 400, never a 500
            log.exception("bot API: malformed input")
            return Response({"detail": "So'rov noto'g'ri."}, status=400)
        return super().handle_exception(exc)

    # ---- who is acting
    @cached_property
    def actor_tg(self) -> int | None:
        return self.request.auth

    @cached_property
    def member(self) -> TelegramMember | None:
        return S.member_by_tg(self.actor_tg) if self.actor_tg else None

    @cached_property
    def employee(self):
        return HR.emp(self.actor_tg) if self.actor_tg else None

    def require_actor(self) -> int:
        if not self.actor_tg:
            raise PermissionDenied("actor required")
        return self.actor_tg

    def require_member(self) -> TelegramMember:
        self.require_actor()
        if not self.member:
            raise PermissionDenied("Siz ro'yxatda yo'qsiz.")
        return self.member

    def require_active(self) -> TelegramMember:
        m = self.require_member()
        if not m.is_active_member:
            raise PermissionDenied("Sizning so'rovingiz hali tasdiqlanmagan yoki bloklangansiz.")
        return m

    def require_admin(self) -> TelegramMember:
        m = self.require_member()
        if not m.is_admin:
            raise PermissionDenied("Bu amal faqat rahbar uchun.")
        return m

    def require_receiver(self) -> TelegramMember:
        m = self.require_active()
        if not (m.is_admin or m.is_bonus_receiver):
            raise PermissionDenied("Bu tugma faqat bonus oluvchi va rahbar uchun.")
        return m

    def require_duty(self, field: str) -> TelegramMember:
        m = self.require_active()
        if not (m.is_admin or getattr(m, field)):
            raise PermissionDenied("Bu amal sizning vazifangiz emas.")
        return m

    def require_hr_admin(self) -> TelegramMember:
        """HR admins are the finance bot's admins."""
        return self.require_admin()

    @property
    def is_admin(self) -> bool:
        return bool(self.member and self.member.is_admin)
