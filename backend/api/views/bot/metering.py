"""Bot API - Zamer: the measurer answers the assignment card in Telegram.

The actor is the panel user linked to the Telegram account; metering.services decides
(every role rule lives there). Files are NOT accepted here: they are uploaded on the
site only. Contract: docs/BOT_CONTRACT.md, "Zamer".
"""

from __future__ import annotations

from rest_framework.exceptions import NotFound, ParseError
from rest_framework.response import Response

from metering import dto
from metering.events import metering_url
from metering.models import Metering
from metering.services import (
    cancel_metering,
    mark_metering_measured,
    metering_queryset_for,
    reschedule_metering,
)

from .base import BotAPIView

PRESETS = ("1h", "tomorrow", "2d")


def _bad(detail: str, field: str | None = None) -> Response:
    body = {"detail": detail}
    if field:
        body["field"] = field
    return Response(body, status=400)


def _dict_body(request) -> dict:
    if not isinstance(request.data, dict):
        raise ParseError("So'rov noto'g'ri.")
    return request.data


class _MeteringView(BotAPIView):
    def get_metering(self, pk) -> Metering:
        # out-of-scope rows are 404, same as a missing one (the bot alerts on both)
        qs = Metering.objects.select_related(
            "client", "measurer", "created_by", "invoice__assigned_to"
        )
        metering = metering_queryset_for(self.require_linked_user(), qs).filter(pk=pk).first()
        if metering is None:
            raise NotFound("Zamer topilmadi")
        return metering


class MeteringMeasuredView(_MeteringView):
    """POST -> {metering: MeteringBrief, url}; 403 not yours, 409 already marked / closed."""

    def post(self, request, pk):
        user = self.require_linked_user()
        metering = mark_metering_measured(self.get_metering(pk), by=user)
        return Response({"metering": dto.metering_brief(metering), "url": metering_url(pk)})


class MeteringRescheduleView(_MeteringView):
    """POST {preset: "1h"|"tomorrow"|"2d"} | {text} -> {metering}; 400 {detail, field: "time"}."""

    def post(self, request, pk):
        user = self.require_linked_user()
        data = _dict_body(request)
        preset, text = data.get("preset"), data.get("text")
        if preset is not None and preset not in PRESETS:
            return _bad("Noma'lum vaqt tanlovi", "time")
        if text is not None and not isinstance(text, str):
            return _bad("Vaqtni tushunmadim", "time")
        metering = reschedule_metering(self.get_metering(pk), by=user, preset=preset, text=text)
        return Response({"metering": dto.metering_brief(metering)})


class MeteringCancelView(_MeteringView):
    """POST {reason} -> {metering, lead_returned}; 400 {detail, field: "reason"}."""

    def post(self, request, pk):
        user = self.require_linked_user()
        data = _dict_body(request)
        reason = data.get("reason")
        if not isinstance(reason, str):
            return _bad("Sababini yozing", "reason")
        metering, returned = cancel_metering(self.get_metering(pk), by=user, reason=reason)
        return Response({"metering": dto.metering_brief(metering), "lead_returned": returned})
