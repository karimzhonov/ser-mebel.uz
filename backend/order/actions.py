from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from unfold.decorators import action
from unfold.enums import ActionVariant

from order.assembly.constants import ASSEMBLY_MANAGER_PERMISSION

from .constants import ORDER_CHANGE_STATUS_PERMISSION, OrderStatus
from .assembly.models import Assembly
from .detailing.models import Detailing
from .models import Order


class OrderActions:
    actions_detail = [
        # 'reverse_status',
        'detailing_action',
        "go_to_assembly_action",
    ]

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
            _("Заказ деталировкага жонатилди"),
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

    # @action(
    #     description=_("Возвращать статус"),
    #     permissions=['reverse_status'],
    #     url_path="reverse-status",
    #     icon='close',
    #     variant=ActionVariant.DANGER
    # )
    # def reverse_status(self, request, object_id):
    #     obj = Order.objects.only('status').get(pk=object_id)
    #     current_status = obj.status
    #     previous_status = OrderStatus.previous_status(current_status)
    #     if previous_status:
    #         obj.change_status(previous_status)
    #         self.message_user(
    #             request,
    #             _(f"Статус изменён с «{OrderStatus(current_status).label}» на «{previous_status.label}».")
    #         )
    #     else:
    #         self.message_user(
    #             request,
    #             _(f"Невозможно возвращать статус: «{OrderStatus(current_status).label}» — начальный."),
    #             level="warning"
    #         )
    #     return redirect(
    #       reverse_lazy("admin:order_order_changelist")
    #     )

    # def has_reverse_status_permission(self, request, object_id):
    #     if not object_id: return False
    #     obj = get_object_or_404(Order, pk=object_id)
    #     return request.user.has_perm(f'order.{ORDER_REVERSE_STATUS_PERMISSION}') and obj.status != OrderStatus.CREATED

    @action(
        description='Отправить в сборку',
        url_path="go-to-assembly",
        variant=ActionVariant.SUCCESS,
        permissions=['go_to_assembly_action']
    )
    def go_to_assembly_action(self, request, object_id):
        obj = get_object_or_404(Order, pk=object_id)
        # `obj.assembly` is a reverse OneToOne: it RAISES RelatedObjectDoesNotExist
        # when there is no Assembly row, so `if obj.assembly` never worked as a guard.
        # Detailing only creates the Assembly when its `square` is non-zero
        # (order/detailing/models.py), so an order detailed with square=0 gets here
        # with nothing to redirect to.
        # Caught by name rather than via getattr(..., None): RelatedObjectDoesNotExist
        # also subclasses AttributeError, so the getattr form would swallow any genuine
        # AttributeError raised while loading the Assembly. Matches order_for_metering
        # in order/admin_display.py.
        try:
            assembly = obj.assembly
        except Assembly.DoesNotExist:
            assembly = None
        if assembly is None:
            # Refuse *before* touching the status: moving the order to ASSEMBLY with no
            # Assembly row strands it in a status whose own button is no longer offered.
            self.message_user(
                request,
                _("Сборка для этого заказа не создана — укажите площадь в деталировке."),
                level="warning"
            )
            return redirect(
              reverse_lazy("admin:order_order_change", kwargs={'object_id': object_id})
            )
        obj.change_status(OrderStatus.ASSEMBLY)
        return redirect(
          reverse_lazy("admin:assembly_assembly_change", kwargs={'object_id': assembly.id})
        )

    def has_go_to_assembly_action_permission(self, request, object_id):
        obj = get_object_or_404(Order, pk=object_id)
        return request.user.has_perm(f'assembly.{ASSEMBLY_MANAGER_PERMISSION}') and obj.status == OrderStatus.WORKING
