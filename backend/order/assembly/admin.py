from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Assembly


@admin.register(Assembly)
class AssemblyAdmin(ModelAdmin):
    list_display = ['order', 'done']
    