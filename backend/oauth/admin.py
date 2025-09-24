from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.models import Group
from django.utils.translation import gettext_lazy as _
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm
from unfold.decorators import action
from core.unfold import ModelAdmin

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    actions_row = ['test_message']
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm
    fieldsets = (
        (None, {"fields": ("phone", "password")}),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (_("Important dates"), {"fields": ("last_login",)}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("phone", "usable_password", "password1", "password2"),
            },
        ),
    )
    list_display = ("phone", "is_staff", "is_superuser", "is_active")
    list_filter = ("is_staff", "is_superuser", "is_active", "groups")
    list_filter_submit = True
    search_fields = ("phone",)
    ordering = ("phone",)
    filter_horizontal = (
        "groups",
        "user_permissions",
    )

    @action(
        description='Test message',
        url_path='test-message',
    )
    def test_message(self, request, object_id):
        user = User.objects.filter(pk=object_id).first()
        if user:
            user.send_message('Test notification')
        return redirect(reverse_lazy("admin:oauth_user_changelist"))


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):
    pass