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
class UFileAdmin(FileAdmin, ModelAdmin):
    fieldsets = ()
    fields = ['preview', 'owner', 'uploaded_at']
    readonly_fields = ['preview', 'owner', 'uploaded_at']
    inlines = [DiscussionInline]

    def get_model_perms(self, request):
        """
        It seems this is only used for the list view. NICE :-)
        """
        return {
            'add': False,
            'change': False,
            'delete': True,
        }
    
    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
    
    @display(description='Файл')
    def preview(self, obj: File):
        return format_html(f'<a href="{obj.file.url}" target="_blank">{obj.original_filename}</a>') if obj.canonical_url else '-'

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                '<path:object_id>/change/',
                self.admin_site.admin_view(self.redirect_to_file),
            ),
        ]
        return custom_urls + urls

    def redirect_to_file(self, request, object_id):
        obj: File = self.get_object(request, object_id)
        file_handle = obj.file.open()

        content_type, _ = mimetypes.guess_type(obj.file.name)

        response = FileResponse(
            file_handle,
            content_type=content_type or 'application/octet-stream'
        )

        response['Content-Disposition'] = "inline; filename*=UTF-8''{}".format(quote(obj.file.name))

        return response


@admin.register(Image)
class UImageAdmin(UFileAdmin):
    fields = ['preview', 'owner', 'uploaded_at']
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
