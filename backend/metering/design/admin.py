from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils.http import urlencode
from django.utils import timezone
from django.http import HttpRequest
from unfold.admin import ModelAdmin
from unfold.decorators import action
from .models import Design


@admin.register(Design)
class DesignAdmin(ModelAdmin):
    list_display = ['metering', 'done']
    actions_detail = ['create_order']

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False
    
    @action(
        description='Создать заказ',
        url_path="create-order",
    )
    def create_order(self, request, object_id: int):
        obj = Design.objects.get(object_id)
        url = reverse_lazy("admin:order_order_add")
        params = urlencode({
            "client": obj.metering.client_id or '',
            "price": obj.price or '',
            "address": obj.metering.address or '',
            "address_link": obj.metering.address_link or '',
            "reception_date": timezone.now().date().strftime('%d.%m.%Y'),
            "metering": obj.metering.pk
        })
        return redirect(f'{url}?{params}')
