from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.shortcuts import get_object_or_404
from unfold.enums import ActionVariant
from unfold.decorators import action
from core.utils.messages import instance_archive
from oauth.constants import METERING_PERMISSION
from oauth.models import User

from .design.models import Design
from .price.models import Price

from .constants import MeteringStatus, METERING_CHANGE_STATUS_PERMISSION
from .models import Metering


REDIRECT = lambda: redirect(reverse_lazy("admin:metering_metering_changelist", query={'status': ','.join(MeteringStatus.active_statuses())}))
REDIRECT_OBJ = lambda object_id: redirect(reverse_lazy("admin:metering_metering_change", kwargs={'object_id': object_id}))

class MeteringActions:
    actions_detail = [
        'create_design', 'create_price', 'action_metering_done', 'action_dont_need'
    ]

    actions_submit_line = [
        'action_other_day'
    ]

    @action(
        description=MeteringStatus.dont_need.label,
        url_path='dont-need',
        icon='close',
        variant=ActionVariant.DANGER,
        permissions=['action_dont_need'],
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
    
    def has_action_dont_need_permission(self, request, object_id):
        obj = Metering.objects.get(pk=object_id)
        return obj.status in [MeteringStatus.created, MeteringStatus.other_day, MeteringStatus.metering_done]
    
    @action(
        description=MeteringStatus.other_day.label,
        url_path='other_day',
        icon='info',
        variant=ActionVariant.PRIMARY,
        permissions=['action_other_day'],
    )
    def action_other_day(self, request, obj: Metering):
        if obj.status in MeteringStatus.archive_statuses():
            instance_archive(request)
            return REDIRECT()

        obj.status=MeteringStatus.other_day
        obj.save(update_fields=['status'])
    
    def has_action_other_day_permission(self, request, object_id):
        if not object_id: return True
        obj = Metering.objects.get(pk=object_id)
        return obj.status in [MeteringStatus.created, MeteringStatus.other_day]

    @action(
        description=MeteringStatus.metering_done.label,
        url_path='metering-done',
        icon='check',
        variant=ActionVariant.SUCCESS,
        permissions=['action_metering_done'],
    )
    def action_metering_done(self, request, object_id):
        obj = get_object_or_404(Metering, pk=object_id)
        if obj.status in MeteringStatus.archive_statuses():
            instance_archive(request)
            return REDIRECT()
        Metering.objects.filter(pk=object_id).update(
            status=MeteringStatus.metering_done
        )
        return REDIRECT()
    
    def has_action_metering_done_permission(self, request, object_id):
        if not request.user.has_perm(f'oauth.{METERING_PERMISSION}'): return False
        obj = Metering.objects.get(pk=object_id)
        return obj.status in [MeteringStatus.created, MeteringStatus.other_day]

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
