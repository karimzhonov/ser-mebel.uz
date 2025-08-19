from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.http import HttpRequest, HttpResponse
from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import RangeDateFilter
from unfold.decorators import display
from simple_history.admin import SimpleHistoryAdmin
from core.utils import get_tag, get_folder_link_html
from core.utils.html import get_boolean_icons

from .actions import MeteringActions
from .filters import MeteringStatusDropdownFilter
from .constants import MeteringStatus
from .models import Metering
from .forms import MeteringCreateForm
from .components import *


@admin.register(Metering)
class MeteringAdmin(MeteringActions, SimpleHistoryAdmin, ModelAdmin):
    list_display = ['client', 'create_date', 'get_status', 'has_design', 'has_price']
    list_filter = [
        MeteringStatusDropdownFilter,
        ('create_date', RangeDateFilter),
    ]
    list_filter_submit = True
    list_before_template = 'metering/metering_list_before.html'
    exclude = ['status', 'folder']

    def has_add_permission(self, request: HttpRequest) -> bool:
        if request.resolver_match.view_name.endswith("changelist"):
            return False
        return True

    def has_delete_permission(self, request: HttpRequest, obj = None) -> bool:
        return False

    def response_add(self, request: HttpRequest, obj: Metering, post_url_continue: str | None = None) -> HttpResponse:
        if request.GET.get('invoice'): return redirect(
            reverse_lazy('admin:call_center_invoice_changelist')
        )
        return super().response_add(request, obj, post_url_continue)

    def get_readonly_fields(self, request, obj = None):
        return ['folder_link', 'design', 'price'] if obj else []
    
    def get_form(self, request, obj=None, **kwargs):
        if not obj:
            kwargs['form'] = MeteringCreateForm
        return super().get_form(request, obj, **kwargs)
    
    @display(
        description='Папка'
    )
    def folder_link(self, obj: Metering):
        return get_folder_link_html(obj.folder_id)

    @display(
        description='Статус'
    )
    def get_status(self, obj: Metering):
        return get_tag(MeteringStatus(obj.status).label, MeteringStatus.variant(obj.status).value)
    
    @display(
        description='Дизайн қилиш'
    )
    def has_design(self, obj: Metering):
        return get_boolean_icons([
            hasattr(obj, 'design') and obj.design,
            hasattr(obj, 'design') and obj.design and obj.design.done,
        ])

    @display(
        description='Нарх чиқариш'
    )
    def has_price(self, obj: Metering):
        return get_boolean_icons([
            hasattr(obj, 'price') and obj.price,
            hasattr(obj, 'price') and obj.price and obj.price.done,
        ])
