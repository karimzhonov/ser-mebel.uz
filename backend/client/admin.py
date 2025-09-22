from django.contrib import admin
from django.http import HttpRequest
from core.unfold import ModelAdmin
from core.filters import get_date_filter
from .models import Client
from .components import *


@admin.register(Client)
class ClientAdmin(ModelAdmin):
    list_display = ['fio', 'phone']
    search_fields = ['fio', 'phone']
    list_filter = [get_date_filter('created_at')]
    list_filter_submit = True

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False
    
    def has_change_permission(self, request: HttpRequest, obj = None) -> bool:
        return False
    
    def has_delete_permission(self, request: HttpRequest, obj = None) -> bool:
        return False
