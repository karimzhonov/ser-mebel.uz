from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse_lazy

from unfold.admin import ModelAdmin
from unfold.contrib.filters.admin import RangeDateFilter
from unfold.dataclasses import UnfoldAction
from unfold.decorators import display

from core.utils import get_tag

from .filters import InvoiceSolutionDropdownFilter
from .constants import SolutionChoice
from .models import Invoice
from .forms import InvoiceCreateForm
from .components import *
 

@admin.register(Invoice)
class InvoiceAdmin(ModelAdmin):
    list_display = ['client', 'create_date', 'get_solution']
    list_filter = [
        InvoiceSolutionDropdownFilter,
        ('create_date', RangeDateFilter),
    ]
    list_filter_submit = True
    list_filter_sheet = False
    list_fullwidth = True
    exclude = ['solution']
    actions_row = SolutionChoice.get_order()
    list_before_template = 'call_center/invoice_list_before.html'
    
    def get_readonly_fields(self, request, obj = None):
        return ['client', 'create_date', 'update_date'] if obj else []

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs['form'] = InvoiceCreateForm
        return super().get_form(request, obj, **kwargs)

    def get_unfold_action(self, action: str) -> UnfoldAction:
        solution = SolutionChoice(action)
        
        def method(request, object_id):
            obj = Invoice.objects.get(pk=object_id)
            obj.solution = solution
            obj.save()
            self.log_change(request, obj, f'Код ответа "{solution}"га ўзгартирилди')
            
            if solution == SolutionChoice.given_location:
                def callback(flag: bool):
                    self.message_user(request, 
                        f'Мижознинг ({obj.client.fio}) {obj.client.phone} рақамига лакация юборилди'
                    ) if flag else self.message_user(request, 
                        f'Мижознинг ({obj.client.fio}) {obj.client.phone} рақамига лакация юборилмади. Техник хато!!!',
                        level=40
                    )
                obj.send_location(callback)

            return redirect(
                reverse_lazy("admin:call_center_invoice_changelist")
            ) 
        
        method.attrs = None
        return UnfoldAction(
            action_name=f"{self.model._meta.app_label}_{self.model._meta.model_name}_{action}",
            method=method,
            description=solution.label,
            path=f"change-solution-{action}",
            icon=SolutionChoice.icon(solution),
            variant=SolutionChoice.variant(solution)
        )
    
    @display(
        description='Код ответа'
    )
    def get_solution(self, obj: Invoice):
        return get_tag(SolutionChoice(obj.solution).label, SolutionChoice.variant(obj.solution).value)
    