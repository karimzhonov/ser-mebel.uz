from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Rover


@admin.register(Rover)
class RoverAdmin(ModelAdmin):
    list_display = ['order', 'done']
