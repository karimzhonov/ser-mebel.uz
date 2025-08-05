from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.http import urlencode
from unfold.dataclasses import UnfoldAction

from .constants import SolutionChoice
from .models import Invoice


class InvoiceActions:
    actions_row = [solution for solution in SolutionChoice.get_order() if solution not in [SolutionChoice.sold_out]]
    
    def _go_for_measured(self, request, obj: Invoice):
        url = reverse_lazy("admin:metering_metering_add")
        params = urlencode({
            "client": obj.client_id or '',
            "invoice": obj.pk
        })
        return redirect(f'{url}?{params}')

    def _given_location_action(self, request, obj: Invoice):
        try:
            # TODO: send location
            self.message_user(request, 
                f'Мижознинг ({obj.client.fio}) {obj.client.phone} рақамига лакация юборилди'
            )
        except ValueError as e:
            self.message_user(request, 
                f'Мижознинг ({obj.client.fio}) {obj.client.phone} рақамига лакация юборилмади. Техник хато!!! {e}',
                level=40
            )

    def get_unfold_action(self, action: str) -> UnfoldAction:
        solution = SolutionChoice(action)
        
        def method(request, object_id):
            obj = Invoice.objects.get(pk=object_id)

            if obj.solution in [SolutionChoice.sold_out, SolutionChoice.go_for_measured]:
                self.message_user(request, 
                    f'Мижозга ({obj.client.fio}) хизмат кўрсатилган',
                    level=30
                )
                return redirect(
                    reverse_lazy("admin:call_center_invoice_changelist")
                ) 
            
            if solution == SolutionChoice.go_for_measured:
                return self._go_for_measured(request, obj)
            
            if solution == SolutionChoice.given_location:
                self._given_location_action(request, obj)
            
            obj.solution = solution
            obj.save()
            self.log_change(request, obj, f'Код ответа "{solution}"га ўзгартирилди')

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
    