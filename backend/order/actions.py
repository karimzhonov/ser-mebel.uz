from django.urls import reverse_lazy
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _
from unfold.enums import ActionVariant
from unfold.decorators import action
from .detailing.models import Detailing
from .models import Order
from .constants import OrderStatus, ORDER_CHANGE_STATUS_PERMISSION, ORDER_REVERSE_STATUS_PERMISSION


class OrderActions:
    actions_row = ['reverse_status']
    actions_detail = ['detailing_action']

    def get_actions_detail(self, request, object_id: int):
        obj = Order.objects.get(pk=object_id)
        return [self.get_unfold_action('detailing_action')] if obj.status == OrderStatus.CREATED else []

    @action(
        description=_('Деталировка'),
        url_path='detailing',
        icon=OrderStatus.icon(OrderStatus.DETAILING),
        variant=ActionVariant.SUCCESS
    )
    def detailing_action(self, request, object_id):
        obj = Order.objects.only('status').get(pk=object_id)
        Detailing.objects.get_or_create(order=obj)
        self.message_user(
            request,
            _(f"Заказ деталировкага жонатилди"),
            level="info"
        )
        obj.change_status(OrderStatus.DETAILING)
        return redirect(
          reverse_lazy("admin:order_order_change", kwargs={'object_id': object_id})
        )

    @action(
        description=_("Изменить статус"),
        permissions=[f'order.{ORDER_CHANGE_STATUS_PERMISSION}'],
        url_path="change-status",
        icon='check',
        variant=ActionVariant.SUCCESS
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
        variant=ActionVariant.DANGER
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
