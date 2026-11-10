"""Rover: the checker's «Tasdiqlash» button (docs/BOT_CONTRACT.md, "Rover")."""

from __future__ import annotations

from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from order.rover.dto import rover_task
from order.rover.models import Rover
from order.rover.services import confirm_rover

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
