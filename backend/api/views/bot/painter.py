"""Painter (molyar): the painter's «Bajardim» and the production head's deadline buttons
(docs/BOT_CONTRACT.md, "Painter")."""

from __future__ import annotations

from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from core.exceptions import ServiceError
from order.painter.dto import painter_part_task, painter_task
from order.painter.models import Painter, PainterPart, PainterType
from order.painter.services import (
    assign_whole_job,
    mark_painter_done,
    mark_part_done,
    set_painter_due,
    set_part_due,
)

from .base import BotAPIView


def _get(pk) -> Painter:
    painter = (
        Painter.objects.select_related("order__client", "done_by")
        .prefetch_related("parts__type__user", "parts__done_by", "parts__due_set_by")
        .filter(pk=pk)
        .first()
    )
    if painter is None:
        raise NotFound("Molyar ishi topilmadi")
    return painter


class PainterDoneView(BotAPIView):
    """POST {note} -> {painter}; 400 {detail, field: "note"} / rover unfinished; 403 not
    linked or not a molyar of the job; 404; 409 already done / the job is split and the
    actor has several open parts. The legacy job-level «Bajardim» (the actor's only open
    part)."""

    def post(self, request, pk):
        user = self.require_linked_user()
        painter = _get(pk)
        data = request.data if isinstance(request.data, dict) else {}
        note = data.get("note")
        if not isinstance(note, str):
            raise ServiceError("Izoh yozing: nima ish qilindi", field="note")
        painter = mark_painter_done(painter, by=user, note=note)
        return Response({"painter": painter_task(painter, viewer=user)})


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
        # the service decides (job done / a team already chosen) under the row lock
        painter = assign_whole_job(painter, ptype, by=user, keep_started=True)
        return Response({"painter": painter_task(painter)})


def _get_part(pk) -> PainterPart:
    part = (
        PainterPart.objects.select_related(
            "painter__order__client", "type__user", "done_by", "due_set_by"
        )
        .filter(pk=pk)
        .first()
    )
    if part is None:
        raise NotFound("Molyar qismi topilmadi")
    return part


def _part_response(part_id) -> Response:
    return Response({"part": painter_part_task(_get_part(part_id))})


class PainterPartDoneView(BotAPIView):
    """POST {note} -> {part}; 400 {detail, field: "note"} / rover unfinished; 403 not linked
    or not the part's molyar (and no `painter.change_painter`); 404; 409 part already
    done. A team's «Bajardim» on its part."""

    def post(self, request, pk):
        user = self.require_linked_user()
        part = _get_part(pk)
        data = request.data if isinstance(request.data, dict) else {}
        note = data.get("note")
        if not isinstance(note, str):
            raise ServiceError("Izoh yozing: nima ish qilindi", field="note")
        mark_part_done(part, by=user, note=note)
        return _part_response(pk)


class PainterPartDueView(BotAPIView):
    """POST {days: 1..30} -> {part}; 400 {detail, field: "due"}; 403 not a production head;
    404; 409 part done. The production head's deadline buttons for one part."""

    def post(self, request, pk):
        user = self.require_site_perm("oauth.user_production_head")
        part = _get_part(pk)
        data = request.data if isinstance(request.data, dict) else {}
        days = data.get("days")
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 30:
            raise ServiceError("Muddat 1 dan 30 kungacha bo'lishi kerak", field="due")
        set_part_due(part, by=user, days=days)
        return _part_response(pk)
