from django.shortcuts import redirect
from django.urls import reverse_lazy
from unfold.enums import ActionVariant
from unfold.decorators import action

from .design.models import Design
from .price.models import Price

from .constants import MeteringStatus
from .models import Metering


class MeteringActions:
    actions_row = [
        'action_dont_need', 'action_other_day', 'action_done'
    ]
    actions_detail = [
        'create_design', 'create_price'
    ]

    @action(
        description=MeteringStatus.dont_need.label,
        url_path='dont-need',
        icon='close',
        variant=ActionVariant.DANGER
    )
    def action_dont_need(self, request, object_id):
        Metering.objects.filter(pk=object_id).update(
            status=MeteringStatus.dont_need
        )
        return redirect(reverse_lazy("admin:metering_metering_changelist"))
    
    @action(
        description=MeteringStatus.other_day.label,
        url_path='other_day',
        icon='info',
        variant=ActionVariant.INFO
    )
    def action_other_day(self, request, object_id):
        Metering.objects.filter(pk=object_id).update(
            status=MeteringStatus.other_day
        )
        return redirect(reverse_lazy("admin:metering_metering_changelist"))

    @action(
        description=MeteringStatus.done.label,
        url_path='done',
        icon='check',
        variant=ActionVariant.SUCCESS
    )
    def action_done(self, request, object_id) :
        Metering.objects.filter(pk=object_id).update(
            status=MeteringStatus.done
        )
        return redirect(reverse_lazy("admin:metering_metering_changelist"))

    @action(
        description='Дизайн қилиш',
        url_path='design',
        icon='design_services',
        variant=ActionVariant.SUCCESS,
    )
    def create_design(self, request, object_id):
        obj = Metering.objects.get(pk=object_id)
        if obj and hasattr(obj, 'design') and obj.design:
            self.message_user(request,
                f'Мижозга ({obj.client.fio}) хизмат кўрсатилган',
                level=30
            ) 
            return redirect(reverse_lazy("admin:metering_metering_change", kwargs={'object_id': object_id}))
        Design.objects.create(metering=obj)
        return redirect(reverse_lazy("admin:metering_metering_change", kwargs={'object_id': object_id}))
    
    @action(
        description='Нарх чикариш',
        url_path='price',
        icon='price_check',
        variant=ActionVariant.PRIMARY,
    )
    def create_price(self, request, object_id):
        obj = Metering.objects.get(pk=object_id)
        if obj and hasattr(obj, 'price') and obj.price:
            self.message_user(request,
                f'Мижозга ({obj.client.fio}) хизмат кўрсатилган',
                level=30
            )
            return redirect(reverse_lazy("admin:metering_metering_change", kwargs={'object_id': object_id}))
        Price.objects.create(metering=obj)
        return redirect(reverse_lazy("admin:metering_metering_change", kwargs={'object_id': object_id}))