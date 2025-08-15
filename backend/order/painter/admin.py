from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Painter


@admin.register(Painter)
class PainterAdmin(ModelAdmin):
    list_display = ['order', 'done']
    