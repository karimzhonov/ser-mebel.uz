from django.contrib import admin
from django.http import HttpRequest
from unfold.admin import ModelAdmin
from .models import Price


@admin.register(Price)
class PriceAdmin(ModelAdmin):
    list_display = ['metering', 'done']

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False
