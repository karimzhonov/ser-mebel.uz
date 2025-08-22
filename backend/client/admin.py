from django.contrib import admin
from django.http import HttpRequest
from unfold.admin import ModelAdmin
from .models import Client
from .components import *


@admin.register(Client)
class ClientAdmin(ModelAdmin):
    list_display = ['fio', 'phone']
    search_fields = ['fio', 'phone']

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False
    
    def has_change_permission(self, request: HttpRequest, obj = None) -> bool:
        return False
    
    def has_delete_permission(self, request: HttpRequest, obj = None) -> bool:
        return False
