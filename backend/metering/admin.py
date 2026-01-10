from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.http import HttpRequest, HttpResponse
from core.unfold import ModelAdmin
from unfold.decorators import display
from simple_history.admin import SimpleHistoryAdmin
from core.utils import get_tag, get_folder_link_html
from core.utils.html import get_boolean_icons
from core.filters import get_date_filter

from .actions import MeteringActions
from .filters import MeteringStatusDropdownFilter
from .constants import MeteringStatus
from .models import Metering
from .forms import MeteringCreateForm
from .components import *


@admin.register(Metering)
class MeteringAdmin(MeteringActions, SimpleHistoryAdmin, ModelAdmin):
    list_display = ['client', 'date_time', 'get_status', 'has_design', 'has_price']
    list_display_links = ['client', 'date_time', 'get_status', 'has_design', 'has_price']
    list_filter = [
        MeteringStatusDropdownFilter,
        get_date_filter('create_date'),
    ]
    list_filter_submit = True
    # list_before_template = 'metering/metering_list_before.html'
    exclude = ['status', 'folder']
    ordering = ['date_time']

    def has_add_permission(self, request: HttpRequest) -> bool:
        if request.resolver_match.view_name.endswith("changelist"):
            return False
        return True
    
    def has_change_permission(self, request, obj: Metering=None):
        if obj and obj.status in MeteringStatus.archive_statuses():
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request: HttpRequest, obj = None) -> bool:
        return False

    def response_add(self, request: HttpRequest, obj: Metering, post_url_continue: str | None = None) -> HttpResponse:
        if request.GET.get('invoice'): return redirect(
            reverse_lazy('admin:call_center_invoice_changelist')
        )
        return super().response_add(request, obj, post_url_continue)

    def get_readonly_fields(self, request, obj = None):
        readonly_fields = ['folder_link', 'invoice', 'address', 'address_link', 'client', 'get_status']
        if obj and hasattr(obj, 'design'):
            readonly_fields.append('design')
        if obj and hasattr(obj, 'price'):
            readonly_fields.append('price')
        return readonly_fields if obj else []
    
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
    
    def get_fieldsets(self, request, obj=None):
        if not obj: return super().get_fieldsets(request, obj)
        fields = ['client', 'invoice', 'address', 'address_link', 'folder_link', 'date_time', 'desc', 'get_status']
        if obj and hasattr(obj, 'design'):
            fields.append('design')
        if obj and hasattr(obj, 'price'):
            fields.append('price')
        return [
            (None, {
                "fields": fields
                })
            ]
