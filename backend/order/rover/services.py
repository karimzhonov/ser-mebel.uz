"""Write services for Rover (used by the REST API; mirror RoverAdmin)."""

from core.exceptions import ServiceError


def mark_rover_done(rover):
    if rover.done:
        raise ServiceError("Ровер аллақачон бажарилган")
    rover.done = True
    rover.save()
    return rover
