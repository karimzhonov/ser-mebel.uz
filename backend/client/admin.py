from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import Client


@admin.register(Client)
class ClientAdmin(ModelAdmin):
    list_display = ['fio', 'phone']
    search_fields = ['fio', 'phone']
