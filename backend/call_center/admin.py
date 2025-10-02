from django.contrib import admin

from core.unfold import ModelAdmin
from unfold.decorators import display

from core.filters import get_date_filter
from core.utils import get_tag

from .actions import InvoiceActions
from .filters import InvoiceSolutionDropdownFilter
from .constants import SolutionChoice
from .models import Invoice
from .forms import InvoiceCreateForm
from .components import *
 

@admin.register(Invoice)
class InvoiceAdmin(InvoiceActions, ModelAdmin):
    list_display = ['client', 'create_date', 'get_solution']
    list_filter = [
        InvoiceSolutionDropdownFilter,
        get_date_filter('create_date'),
    ]
    list_filter_submit = True
    list_filter_sheet = False
    list_fullwidth = True
    exclude = ['solution']
    list_before_template = 'call_center/invoice_list_before.html'

    def get_readonly_fields(self, request, obj = None):
        return ['client', 'create_date', 'update_date'] if obj else []

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs['form'] = InvoiceCreateForm
        return super().get_form(request, obj, **kwargs)

    @display(
        description='Код ответа'
    )
    def get_solution(self, obj: Invoice):
        return get_tag(SolutionChoice(obj.solution).label, SolutionChoice.variant(obj.solution).value) if obj.solution else '-'
    
    def has_add_permission(self, request):
        return request.user.has_perm('call_center.add_invoice')

    def has_change_permission(self, request, obj = None):
        if obj and obj.solution in [SolutionChoice.sold_out, SolutionChoice.go_for_measured, SolutionChoice.price_problem, SolutionChoice.dont_need, SolutionChoice.declined]:
            return False
        return super().has_change_permission(request, obj)