"""Order -> Готов starts the finance follow-up at once (the «Готов» payment sheet to the
bonus receiver) instead of waiting for the next hourly pass, which stays as a fallback."""

import logging

from django.db import transaction
from django.db.models.signals import post_save, pre_save

log = logging.getLogger("finance.signals")


def _remember_status(sender, instance, raw=False, **kwargs):
    from order.constants import OrderStatus

    instance._fin_was_done = bool(
        not raw
        and instance.pk
        and instance.status == OrderStatus.DONE
        and sender.objects.filter(pk=instance.pk, status=OrderStatus.DONE).exists()
    )


def _order_saved(sender, instance, raw=False, **kwargs):
    from order.constants import OrderStatus

    if raw or instance.status != OrderStatus.DONE or getattr(instance, "_fin_was_done", False):
        return
    if not instance.order_number:
        return
    ref = str(instance.order_number)

    def queue():
        from .tasks import order_ready

        order_ready.delay(ref)

    # robust: a broker hiccup must not break the order save; the hourly pass catches up
    transaction.on_commit(queue, robust=True)


def connect():
    from order.models import Order

    pre_save.connect(_remember_status, sender=Order, dispatch_uid="fin_order_status")
    post_save.connect(_order_saved, sender=Order, dispatch_uid="fin_order_ready")
