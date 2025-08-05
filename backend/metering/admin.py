from typing import Any
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.http import HttpRequest, HttpResponse
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import RangeDateFilter
from unfold.decorators import display

from core.utils import get_tag

from .actions import MeteringActions
from .filters import MeteringStatusDropdownFilter
from .constants import MeteringStatus
from .models import Metering
from .forms import MeteringCreateForm, MeteringFromCallCenterForm
from .components import *


@admin.register(Metering)
class MeteringAdmin(MeteringActions, ModelAdmin):
    list_display = ['client', 'create_date', 'get_status']
    list_filter = [
        MeteringStatusDropdownFilter,
        ('create_date', RangeDateFilter),
    ]
    list_filter_submit = True
    list_before_template = 'metering/metering_list_before.html'
    
    def get_exclude(self, request: HttpRequest, obj: Metering=None) -> Any:
        return ['status'] if obj and obj.price else ['currency', 'price', 'status']

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs['form'] = MeteringFromCallCenterForm if request.GET.get('invoice') else MeteringCreateForm
        return super().get_form(request, obj, **kwargs)

    @display(
        description='Статус'
    )
    def get_status(self, obj: Metering):
        return get_tag(MeteringStatus(obj.status).label, MeteringStatus.variant(obj.status).value)
    
    def response_add(self, request: HttpRequest, obj: Metering, post_url_continue: str | None = None) -> HttpResponse:
        if request.GET.get('invoice'): return redirect(
            reverse_lazy('admin:call_center_invoice_changelist')
        )
        return super().response_add(request, obj, post_url_continue)