import os
import mimetypes
from urllib.parse import quote
from django.contrib import admin
from django.urls import path
from django.http import FileResponse
from django.utils.html import format_html
from filer.models import File, Folder, FolderPermission, ThumbnailOption, Image
from filer.admin import FileAdmin, FolderAdmin, PermissionAdmin
from unfold.decorators import display
from core.unfold import ModelAdmin
from discussion.inlines import DiscussionInline

admin.site.unregister(Folder)
admin.site.unregister(File)
admin.site.unregister(Image)
admin.site.unregister(FolderPermission)
admin.site.unregister(ThumbnailOption)
admin.site.index_template = 'index.html'


@admin.register(Folder)
class UFolderAdmin(FolderAdmin, ModelAdmin):
    inlines = [DiscussionInline]


@admin.register(File)
class UFileAdmin(FileAdmin):
    readonly_fields = ['preview', 'owner', 'uploaded_at']

    @admin.display(description='Файл')
    def preview(self, obj: File):
        return format_html(
            '<a href="{}" target="_blank">Открыть файл</a>',
            f'preview/{obj.pk}/'
        )

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                '<path:object_id>/change/',
                self.admin_site.admin_view(self.preview_file),
                name='filer_preview',
            ),
        ]
        return custom_urls + urls

    def preview_file(self, request, object_id):
        obj = File.objects.get(pk=object_id)

        content_type, _ = mimetypes.guess_type(obj.file.name)

        response = FileResponse(
            obj.file.open('rb'),
            content_type=content_type or 'application/octet-stream',
            as_attachment=False,
            filename=obj.file.name
        )

        response['Content-Disposition'] = (
            "inline; filename*=UTF-8''{}".format(quote(obj.file.name))
        )

        return response


@admin.register(Image)
class UImageAdmin(UFileAdmin):
    # fields = ['preview', 'owner', 'uploaded_at']
    readonly_fields = ['preview', 'owner', 'uploaded_at']
    
    @display(image=True, description='Фото')
    def preview(self, obj: Image):
        return format_html(f'<a href="{obj.file.url}" target="_blank"><img src="{obj.canonical_url}" class="max-w-lg w-full" /></a>') if obj.canonical_url else '-'


@admin.register(FolderPermission)
class UFolderPermissionAdmin(ModelAdmin, PermissionAdmin):
    pass


@admin.register(ThumbnailOption)
class UThumbnailOptionAdmin(ModelAdmin):
    list_display = ('name', 'width', 'height')
    search_fields = ['name']


# --- Celery: beat schedule + task results («Фоновые задачи» in the sidebar, superusers).
# The packages register plain Django admins; re-register them on unfold's ModelAdmin.
from django_celery_beat.admin import PeriodicTaskAdmin as BasePeriodicTaskAdmin
from django_celery_beat.models import (
    ClockedSchedule,
    CrontabSchedule,
    IntervalSchedule,
    PeriodicTask,
    SolarSchedule,
)
from django_celery_results.admin import GroupResultAdmin as BaseGroupResultAdmin
from django_celery_results.admin import TaskResultAdmin as BaseTaskResultAdmin
from django_celery_results.models import GroupResult, TaskResult

for _model in (PeriodicTask, IntervalSchedule, CrontabSchedule, SolarSchedule, ClockedSchedule, TaskResult, GroupResult):
    admin.site.unregister(_model)


@admin.register(PeriodicTask)
class UPeriodicTaskAdmin(BasePeriodicTaskAdmin, ModelAdmin):
    pass


@admin.register(CrontabSchedule)
class UCrontabScheduleAdmin(ModelAdmin):
    list_display = ('__str__',)


@admin.register(TaskResult)
class UTaskResultAdmin(BaseTaskResultAdmin, ModelAdmin):
    list_display = ('task_name', 'periodic_task_name', 'status', 'date_created', 'date_done', 'result')
    list_filter = ('status', 'task_name', 'periodic_task_name', 'date_done')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(GroupResult)
class UGroupResultAdmin(BaseGroupResultAdmin, ModelAdmin):
    pass
