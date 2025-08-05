from django.urls import reverse_lazy
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _

from unfold.decorators import action

from .models import Order
from .constants import OrderStatus, ORDER_CHANGE_STATUS_PERMISSION, ORDER_REVERSE_STATUS_PERMISSION


class OrderActions:
    actions_row = ['change_status', 'reverse_status']

    @action(
        description=_("Изменить статус"),
        permissions=[f'order.{ORDER_CHANGE_STATUS_PERMISSION}'],
        url_path="change-status",
        icon='check',
        variant='success'
    )
    def change_status(self, request, object_id):
        obj = Order.objects.only('status').get(pk=object_id)
        current_status = obj.status
        next_status = OrderStatus.next_status(current_status)

        if next_status:
            obj.change_status(next_status)
            self.message_user(
                request,
                _(f"Статус изменён с «{OrderStatus(current_status).label}» на «{next_status.label}».")
            )
        else:
            self.message_user(
                request,
                _(f"Невозможно изменить статус: «{OrderStatus(current_status).label}» — финальный."),
                level="warning"
            )
        return redirect(
          reverse_lazy("admin:order_order_changelist")
        )
    
    @action(
        description=_("Возвращать статус"),
        permissions=[f'order.{ORDER_REVERSE_STATUS_PERMISSION}'],
        url_path="reverse-status",
        icon='close',
        variant='danger'
    )
    def reverse_status(self, request, object_id):
        obj = Order.objects.only('status').get(pk=object_id)
        current_status = obj.status
        previous_status = OrderStatus.previous_status(current_status)
        if previous_status:
            obj.change_status(previous_status)
            self.message_user(
                request,
                _(f"Статус изменён с «{OrderStatus(current_status).label}» на «{previous_status.label}».")
            )
        else:
            self.message_user(
                request,
                _(f"Невозможно возвращать статус: «{OrderStatus(current_status).label}» — начальный."),
                level="warning"
            )
        return redirect(
          reverse_lazy("admin:order_order_changelist")
        )
