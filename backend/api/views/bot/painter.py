"""Painter (molyar): the painter's «Bajardim» and the production head's deadline buttons
(docs/BOT_CONTRACT.md, "Painter")."""

from __future__ import annotations

from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from core.exceptions import ServiceConflict, ServiceError
from order.painter.dto import painter_task
from order.painter.models import Painter, PainterType
from order.painter.services import assign_painter_type, mark_painter_done, set_painter_due

from .base import BotAPIView


def _get(pk) -> Painter:
    painter = (
        Painter.objects.select_related("order__client", "type__user", "done_by", "due_set_by")
        .filter(pk=pk)
        .first()
    )
    if painter is None:
        raise NotFound("Molyar ishi topilmadi")
    return painter


class PainterDoneView(BotAPIView):
    """POST {note} -> {painter}; 400 {detail, field: "note"} / rover unfinished; 403 not
    linked or not the assignee; 404; 409 already done. The painter's «Bajardim»."""

    def post(self, request, pk):
        user = self.require_linked_user()
        painter = _get(pk)
        data = request.data if isinstance(request.data, dict) else {}
        note = data.get("note")
        if not isinstance(note, str):
            raise ServiceError("Izoh yozing: nima ish qilindi", field="note")
        painter = mark_painter_done(painter, by=user, note=note)
        return Response({"painter": painter_task(painter)})


class PainterDueView(BotAPIView):
    """POST {days: 1..30} -> {painter}; 400 {detail, field: "due"}; 403; 404; 409 done.
    The production head's deadline buttons."""

    def post(self, request, pk):
        user = self.require_site_perm("oauth.user_production_head")
        painter = _get(pk)
        data = request.data if isinstance(request.data, dict) else {}
        days = data.get("days")
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 30:
            raise ServiceError("Muddat 1 dan 30 kungacha bo'lishi kerak", field="due")
        painter = set_painter_due(painter, by=user, days=days)
        return Response({"painter": painter_task(painter)})


class PainterTypeView(BotAPIView):
    """POST {type_id} -> {painter}; 403 not linked / not a production head; 404 painter or
    team missing; 400 rover unfinished / team without a molyar; 409 job done / a different team already chosen after start. The head picks
    the team after the rover."""

    def post(self, request, pk):
        user = self.require_site_perm("oauth.user_production_head")
        painter = _get(pk)
        data = request.data if isinstance(request.data, dict) else {}
        type_id = data.get("type_id")
        ptype = None
        if isinstance(type_id, int) and not isinstance(type_id, bool):
            ptype = PainterType.objects.select_related("user").filter(pk=type_id).first()
        if ptype is None:
            raise NotFound("Molyar yoki jamoa topilmadi")
        if painter.done:
            raise ServiceConflict("Molyar ishi bajarilgan")
        if painter.type_id and painter.started_at and painter.type_id != ptype.pk:
            raise ServiceConflict(
                f"Jamoa allaqachon tanlangan: {painter.type.name} — o'zgartirish saytda"
            )
        # the service re-checks «already started» under the row lock (two heads at once)
        painter = assign_painter_type(painter, ptype, by=user, keep_started=True)
        return Response({"painter": painter_task(painter)})
