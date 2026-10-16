from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.models import Group, Permission
from django.utils.translation import gettext_lazy as _
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm
from unfold.decorators import action
from unfold.admin import ModelAdmin

from .models import User
from .services import TEST_MESSAGE_TEXT, send_test_telegram_messages


admin.site.unregister(Group)


@admin.register(Permission)
class AuthPermissionAdmin(ModelAdmin):
    list_display = ['name', 'codename', 'content_type']
    search_fields = ['codename']


@admin.register(User)
class UserAdmin(BaseUserAdmin, ModelAdmin):
    actions = ['send_test_message_action']
    actions_row = ['test_message']
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm
    fieldsets = (
        (None, {"fields": ("phone", "name", "telegram_id", "password")}),
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
    list_display = ("name", "phone", "is_staff", "is_superuser", "is_active")
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
            # text=, not positional: send_message's first argument is `url`.
            user.send_message(text=TEST_MESSAGE_TEXT)
        return redirect(reverse_lazy("admin:oauth_user_changelist"))

    @admin.action(description=_('Отправить тестовое сообщение в Telegram'))
    def send_test_message_action(self, request, queryset):
        sent, without_telegram, failed = send_test_telegram_messages(queryset)

        # Plain f-strings, not _(): gettext cannot extract from an f-string.
        if sent:
            self.message_user(request, f'Отправлено: {sent}.', level='success')
        if without_telegram:
            self.message_user(
                request,
                f'Без привязанного Telegram: {without_telegram}.',
                level='warning',
            )
        if failed:
            self.message_user(
                request,
                f'Не доставлено (бот недоступен): {failed}.',
                level='error',
            )


@admin.register(Group)
class GroupAdmin(BaseGroupAdmin, ModelAdmin):
    
    def has_add_permission(self, request):
        return super(ModelAdmin, self).has_add_permission(request)