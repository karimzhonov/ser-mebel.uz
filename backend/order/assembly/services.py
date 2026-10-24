"""Write services for Assembly (used by the REST API; mirror AssemblyAdmin)."""

from django.db import models, transaction

from core.exceptions import ServiceError
from oauth.constants import ASSEMBLY_PERMISSION

from ..constants import OrderStatus


def assemblers():
    """Users who may be picked as "Сборщик" (AssemblyForm's queryset)."""
    from oauth.models import User

    return User.objects.filter(
        models.Q(user_permissions__codename=ASSEMBLY_PERMISSION)
        | models.Q(groups__permissions__codename=ASSEMBLY_PERMISSION)
    ).distinct()


def mark_assembly_done(assembly):
    """Mirrors AssemblyAdmin.done_action: the order moves to "Установка"."""
    if assembly.done:
        raise ServiceError("Сборка аллақачон бажарилган")
    with transaction.atomic():
        assembly.done = True
        assembly.save(update_fields=["done"])
        assembly.order.status = OrderStatus.INSTALLING
        assembly.order.save(update_fields=["status"])
    return assembly


def mark_installing_done(assembly):
    """Mirrors AssemblyAdmin.installing_done_action: the order is finished."""
    if not assembly.done:
        raise ServiceError("Аввал сборкани бажаринг")
    if assembly.installing_done:
        raise ServiceError("Установка аллақачон бажарилган")
    with transaction.atomic():
        assembly.installing_done = True
        assembly.save(update_fields=["installing_done"])
        assembly.order.status = OrderStatus.DONE
        assembly.order.save(update_fields=["status"])
    return assembly
