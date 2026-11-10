"""Celery tasks of the Rover flow."""

from celery import shared_task


@shared_task
def notify_painting_ready_task(rover_id):
    """Tell the painter side that milling is done. Once per rover (redelivery-safe)."""
    from accounting.services import once

    from .models import Rover
    from .services import notify_painting_ready

    rover = Rover.objects.select_related("order").filter(pk=rover_id, done=True).first()
    if rover is None or not once(f"rover:{rover_id}:painting_ready"):
        return False
    notify_painting_ready(rover.order)
    return True
