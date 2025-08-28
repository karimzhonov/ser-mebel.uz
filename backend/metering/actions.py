from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.shortcuts import get_object_or_404
from unfold.enums import ActionVariant
from unfold.decorators import action
from core.utils.messages import instance_archive
from .design.models import Design
from .price.models import Price

from .constants import MeteringStatus, METERING_CHANGE_STATUS_PERMISSION
from .models import Metering


REDIRECT = lambda: redirect(reverse_lazy("admin:metering_metering_changelist", query={'status': ','.join(MeteringStatus.active_statuses())}))
REDIRECT_OBJ = lambda object_id: redirect(reverse_lazy("admin:metering_metering_change", kwargs={'object_id': object_id}))

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
        variant=ActionVariant.DANGER,
        permissions=[f'metering.{METERING_CHANGE_STATUS_PERMISSION}'],
    )
    def action_dont_need(self, request, object_id):
        obj = get_object_or_404(Metering, pk=object_id)
        if obj.status in MeteringStatus.archive_statuses():
            instance_archive(request)
            return REDIRECT()
        Metering.objects.filter(pk=object_id).update(
            status=MeteringStatus.dont_need
        )
        return REDIRECT()
    
    @action(
        description=MeteringStatus.other_day.label,
        url_path='other_day',
        icon='info',
        variant=ActionVariant.INFO,
        permissions=[f'metering.{METERING_CHANGE_STATUS_PERMISSION}'],
    )
    def action_other_day(self, request, object_id):
        obj = get_object_or_404(Metering, pk=object_id)
        if obj.status in MeteringStatus.archive_statuses():
            instance_archive(request)
            return REDIRECT()
        Metering.objects.filter(pk=object_id).update(
            status=MeteringStatus.other_day
        )
        return REDIRECT()

    @action(
        description=MeteringStatus.done.label,
        url_path='done',
        icon='check',
        variant=ActionVariant.SUCCESS,
        permissions=[f'metering.{METERING_CHANGE_STATUS_PERMISSION}'],
    )
    def action_done(self, request, object_id):
        obj = get_object_or_404(Metering, pk=object_id)
        if obj.status in MeteringStatus.archive_statuses():
            instance_archive(request)
            return REDIRECT()
        Metering.objects.filter(pk=object_id).update(
            status=MeteringStatus.done
        )
        return REDIRECT()

    @action(
        description='Дизайн қилиш',
        url_path='design',
        icon='design_services',
        variant=ActionVariant.SUCCESS,
        permissions=['create_design'],
    )
    def create_design(self, request, object_id):
        obj = Metering.objects.get(pk=object_id)
        if obj and hasattr(obj, 'design') and obj.design:
            instance_archive(request)
            return REDIRECT_OBJ(object_id)
        Design.objects.create(metering=obj)
        return REDIRECT_OBJ(object_id)
    
    def has_create_design_permission(self, request, object_id):
        obj = Metering.objects.get(pk=object_id)
        return request.user.has_perm('design.add_design') and not hasattr(obj, 'design')
    
    @action(
        description='Нарх чикариш',
        url_path='price',
        icon='price_check',
        variant=ActionVariant.PRIMARY,
        permissions=['create_price']
    )
    def create_price(self, request, object_id):
        obj = Metering.objects.get(pk=object_id)
        if obj and hasattr(obj, 'price') and obj.price:
            instance_archive(request)
            return REDIRECT_OBJ(object_id)
        Price.objects.create(metering=obj)
        return REDIRECT_OBJ(object_id)

    def has_create_price_permission(self, request, object_id):
        obj = Metering.objects.get(pk=object_id)
        return request.user.has_perm('price.add_price') and not hasattr(obj, 'price')
