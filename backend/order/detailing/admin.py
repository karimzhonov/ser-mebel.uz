from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Detailing

@admin.register(Detailing)
class DetailingAdmin(ModelAdmin):
    list_display = ['order', 'done']
