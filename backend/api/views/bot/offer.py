"""Bot API - Dizayn va narx: the designer / pricer moves the deadline, the manager records
the client's answer in Telegram. «Tayyor» is NEVER here: it is pressed on the site only.

The actor is the panel user linked to the Telegram account; metering.services /
design.services / price.services decide (every role rule lives there).
Contract: docs/BOT_CONTRACT.md, "Dizayn va narx".
"""

from __future__ import annotations

from rest_framework.exceptions import NotFound, ParseError
from rest_framework.response import Response

from metering import dto
from metering.design.models import Design
from metering.design.services import can_work_design, record_design_answer, set_design_due
from metering.price.models import Price
from metering.price.services import can_work_price, record_price_answer, set_price_due
from metering.services import can_present

from .base import BotAPIView


def _dict_body(request) -> dict:
    if not isinstance(request.data, dict):
        raise ParseError("So'rov noto'g'ri.")
    return request.data


def _bad(detail: str, field: str) -> Response:
    return Response({"detail": detail, "field": field}, status=400)


class _OfferView(BotAPIView):
    def get_row(self, kind, pk, user):
        """The Design / Price, if this person has anything to do with it; out-of-scope
        rows are 404, same as a missing one (the bot alerts on both)."""
        if kind not in ("design", "price"):
            raise NotFound("Topilmadi")
        model = Design if kind == "design" else Price
        can_work = can_work_design if kind == "design" else can_work_price
        row = (
            model.objects.select_related(
                "metering__client", "metering__manager", "metering__measurer", "user"
            )
            .filter(pk=pk, metering__isnull=False)
            .first()
        )
        if row is None or not (
            row.user_id == user.pk
            or can_work(user, row)
            or can_present(user, row.metering)
            or user.has_perm("metering.manage_metering")
        ):
            raise NotFound("Topilmadi")
        return row


class OfferDueView(_OfferView):
    """POST {preset: "1d"|"2d"|"3d"} | {text} -> {task: OfferTask}; 400 {detail, field:
    "due"}; 403 not yours; 409 not in work."""

    def post(self, request, kind, pk):
        user = self.require_linked_user()
        data = _dict_body(request)
        preset, text = data.get("preset"), data.get("text")
        if (preset is not None and not isinstance(preset, str)) or (
            text is not None and not isinstance(text, str)
        ):
            return _bad("Muddatni tushunmadim", "due")
        row = self.get_row(kind, pk, user)
        mover = set_design_due if kind == "design" else set_price_due
        row = mover(row, by=user, preset=preset, text=text)
        return Response({"task": dto.offer_task(row, kind)})


class OfferAnswerView(_OfferView):
    """POST {answer, comment?} -> {task, closed_tasks}; design approved|changes|declined,
    price approved|recalc|declined. 400 {detail, field: "answer"|"comment"}; 403 not the
    manager; 409 already answered. A «changes» / «recalc» answer uses the default fix
    deadline (the assignee can move it)."""

    def post(self, request, kind, pk):
        user = self.require_linked_user()
        data = _dict_body(request)
        answer, comment = data.get("answer"), data.get("comment", "")
        if not isinstance(answer, str):
            return _bad("Javobni tanlang", "answer")
        if comment is None:
            comment = ""
        if not isinstance(comment, str):
            return _bad("Izoh matn bo'lishi kerak", "comment")
        row = self.get_row(kind, pk, user)
        record = record_design_answer if kind == "design" else record_price_answer
        result = record(row, by=user, answer=answer, comment=comment)
        return Response(
            {"task": dto.offer_task(result["task"], kind), "closed_tasks": result["closed_tasks"]}
        )
