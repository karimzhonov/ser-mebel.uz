from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.http import urlencode
from django.utils import timezone
from unfold.dataclasses import UnfoldAction

from .constants import MeteringStatus
from .models import Metering


class MeteringActions:
    actions_row = [status for status in MeteringStatus.get_order() if not status == MeteringStatus.created]

    def _sold_out(self, request, obj: Metering):
        url = reverse_lazy("admin:order_order_add")
        params = urlencode({
            "client": obj.client_id or '',
            "price": obj.price or '',
            "address": obj.address or '',
            "address_link": obj.address_link or '',
            "reception_date": timezone.now().date().strftime('%d.%m.%Y'),
            "metering": obj.pk
        })
        return redirect(f'{url}?{params}')

    def get_unfold_action(self, action: str) -> UnfoldAction:
        status = MeteringStatus(action)
        
        def method(request, object_id):
            obj = Metering.objects.get(pk=object_id)

            if obj.status in [MeteringStatus.sold_out]:
                self.message_user(request, 
                    f'Мижозга ({obj.client.fio}) хизмат кўрсатилган',
                    level=30
                ) 
                return redirect(
                    reverse_lazy("admin:metering_metering_changelist")
                ) 
            if status == MeteringStatus.sold_out:
                return self._sold_out(request, obj)
            
            obj.status = status
            obj.save()
            self.log_change(request, obj, f'Статус "{status}"га ўзгартирилди')
            
            return redirect(
                reverse_lazy("admin:metering_metering_changelist")
            ) 
        
        method.attrs = None
        return UnfoldAction(
            action_name=f"{self.model._meta.app_label}_{self.model._meta.model_name}_{action}",
            method=method,
            description=status.label,
            path=f"change-status-{action}",
            icon=MeteringStatus.icon(status),
            variant=MeteringStatus.variant(status)
        )
    