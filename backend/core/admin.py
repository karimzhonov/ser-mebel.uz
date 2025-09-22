from django.contrib import admin
from django.contrib.auth.models import Group, Permission
from django.utils.html import format_html
from filer.models import File, Folder, FolderPermission, ThumbnailOption, Image
from filer.admin import FileAdmin, FolderAdmin, PermissionAdmin
from unfold.decorators import display
from core.unfold import ModelAdmin
from discussion.inlines import DiscussionInline

admin.site.unregister(Group)
admin.site.unregister(Folder)
admin.site.unregister(File)
admin.site.unregister(Image)
admin.site.unregister(FolderPermission)
admin.site.unregister(ThumbnailOption)
admin.site.index_template = 'index.html'



@admin.register(Permission)
class AuthPermissionAdmin(ModelAdmin):
    list_display = ['name', 'codename', 'content_type']
    search_fields = ['codename']


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
            'delete': False,
        }
    
    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
    
    @display(description='Файл')
    def preview(self, obj: File):
        return format_html(f'<a href="{obj.canonical_url}" target="_blank">{obj.original_filename}</a>') if obj.canonical_url else '-'



@admin.register(Image)
class UImageAdmin(UFileAdmin):
    fields = ['preview', 'owner', 'uploaded_at']
    readonly_fields = ['preview', 'owner', 'uploaded_at']
    
    @display(image=True, description='Фото')
    def preview(self, obj: Image):
        return format_html(f'<a href="{obj.canonical_url}" target="_blank"><img src="{obj.canonical_url}" class="max-w-lg w-full" /></a>') if obj.canonical_url else '-'


@admin.register(FolderPermission)
class UFolderPermissionAdmin(ModelAdmin, PermissionAdmin):
    pass


@admin.register(ThumbnailOption)
class UThumbnailOptionAdmin(ModelAdmin):
    list_display = ('name', 'width', 'height')
    search_fields = ['name']
