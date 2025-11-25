from django.urls import reverse_lazy
from django.shortcuts import redirect, get_object_or_404
from django.utils.translation import gettext_lazy as _
from unfold.enums import ActionVariant
from unfold.decorators import action
from .detailing.models import Detailing
from .models import Order
from .constants import OrderStatus, ORDER_CHANGE_STATUS_PERMISSION, ORDER_REVERSE_STATUS_PERMISSION


class OrderActions:
    actions_detail = ['reverse_status', 'detailing_action']

    @action(
        description=_('Деталировка'),
        url_path='detailing',
        icon=OrderStatus.icon(OrderStatus.DETAILING),
        variant=ActionVariant.SUCCESS,
        permissions=['detailing_action']
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
    
    def has_detailing_action_permission(self, request, object_id):
        obj = get_object_or_404(Order, pk=object_id)
        return request.user.has_perm('detailing.add_detailing') and obj.status == OrderStatus.CREATED

    @action(
        description=_("Изменить статус"),
        permissions=['change_status'],
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
    
    def has_change_status_permission(self, request, object_id):
        obj = get_object_or_404(Order, pk=object_id)
        return request.user.has_perm(f'order.{ORDER_CHANGE_STATUS_PERMISSION}') and obj.status != OrderStatus.DONE
    
    @action(
        description=_("Возвращать статус"),
        permissions=['reverse_status'],
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

    def has_reverse_status_permission(self, request, object_id):
        if not object_id: return False
        obj = get_object_or_404(Order, pk=object_id)
        return request.user.has_perm(f'order.{ORDER_REVERSE_STATUS_PERMISSION}') and obj.status != OrderStatus.CREATED