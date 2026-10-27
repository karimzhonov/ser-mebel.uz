"""Bot API: who is this Telegram user (whoami) and site-account linking (link)."""

from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response

from accounting import services as S
from core.exceptions import ServiceError
from hr import services as HR
from oauth.services import link_telegram

from ...serializers import bot as D
from .base import BotAPIView


class WhoAmIView(BotAPIView):
    """POST {user: {id, username, first_name, last_name}} -> the sender's roles.
    Side effects: the finance member's username is refreshed; an employee who writes
    to the bot can be written back (can_dm)."""

    def post(self, request):
        user = request.data.get("user") or {}
        tg = user.get("id")
        try:
            same = tg is not None and int(tg) == self.require_actor()
        except (TypeError, ValueError):
            raise ServiceError("user.id noto'g'ri.")
        if not same:
            raise PermissionDenied("actor mismatch")
        m = S.touch_member_username(tg, user.get("username") or "")
        e = HR.emp(tg)
        if e:
            HR.mark_dm_ok(e)
        return Response(
            {
                "finance_member": D.member_dto(m) if m else None,
                "hr": {
                    "employee": D.employee_dto(e) if e else None,
                    "is_admin": bool(m and m.is_admin),
                },
            }
        )


class LinkView(BotAPIView):
    """POST {token, telegram_id}: `/start <payload>` from the site's "connect Telegram"
    link. No actor; the signed token proves which site user it is."""

    def post(self, request):
        try:
            tg = int(request.data.get("telegram_id"))
        except (TypeError, ValueError):
            raise NotFound()
        user = link_telegram(request.data.get("token"), tg)
        if user is None:
            raise NotFound()
        return Response(
            {"linked": True, "user": {"id": user.pk, "name": user.name or str(user.phone)}}
        )
