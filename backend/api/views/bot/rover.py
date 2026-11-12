"""Rover: the checker's «Tasdiqlash» button (docs/BOT_CONTRACT.md, "Rover")."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from djmoney.money import Money
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from core.exceptions import ServiceError
from order.rover.dto import rover_task
from order.rover.models import Rover
from order.rover.services import confirm_rover, set_rover_due, submit_rover

from .base import BotAPIView


class RoverConfirmView(BotAPIView):
    """POST {} -> {rover}; 403 not linked / no right; 409 already confirmed; 400 not handed in."""

    def post(self, request, pk):
        user = self.require_site_perm("oauth.user_rover_checker")
        rover = Rover.objects.filter(pk=pk).first()
        if rover is None:
            raise NotFound("Rover topilmadi")
        rover = confirm_rover(rover, by=user)
        return Response({"rover": rover_task(rover)})


class RoverSubmitView(BotAPIView):
    """POST {amount, note} -> {rover}; 400 {detail, field: "amount"|"note"}; 403; 404;
    409 already handed in / done. The worker's «Bajardim»."""

    def post(self, request, pk):
        user = self.require_site_perm("rover.change_rover")
        rover = Rover.objects.filter(pk=pk).first()
        if rover is None:
            raise NotFound("Rover topilmadi")
        data = request.data if isinstance(request.data, dict) else {}
        raw = data.get("amount")
        try:
            if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
                raise InvalidOperation
            # Rover.price is MoneyField(max_digits=12, 2 decimals): same cap as api/fields.py.
            amount = Decimal(str(raw).strip().replace(" ", ""))
            if not amount.is_finite() or amount <= 0 or amount >= Decimal(10) ** 10:
                raise InvalidOperation
            amount = amount.quantize(Decimal("0.01"))
        except InvalidOperation:
            raise ServiceError("Summa 0 dan katta bo'lishi kerak", field="amount")
        note = data.get("note")
        if not isinstance(note, str):
            raise ServiceError("Izoh yozing: nima ish qilindi, nechta eshik", field="note")
        try:
            rover = submit_rover(rover, by=user, price=Money(amount, "UZS"), note=note)
        except ServiceError as e:
            if e.field == "price":
                e.field = "amount"
            raise
        return Response({"rover": rover_task(rover)})


class RoverDueView(BotAPIView):
    """POST {days: 1..30} -> {rover}; 400 {detail, field: "due"}; 403; 404; 409 done.
    The production head's deadline buttons."""

    def post(self, request, pk):
        user = self.require_site_perm("oauth.user_production_head")
        rover = Rover.objects.filter(pk=pk).first()
        if rover is None:
            raise NotFound("Rover topilmadi")
        data = request.data if isinstance(request.data, dict) else {}
        days = data.get("days")
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 30:
            raise ServiceError("Muddat 1 dan 30 kungacha bo'lishi kerak", field="due")
        rover = set_rover_due(rover, by=user, days=days)
        return Response({"rover": rover_task(rover)})
