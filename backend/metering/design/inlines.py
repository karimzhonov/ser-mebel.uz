from unfold.admin import StackedInline
from unfold.decorators import display
from core.utils import get_folder_link_html
from .models import Design


class DesignInline(StackedInline):
    model = Design
    extra = 0
    fk_name = 'metering'
    fields = ['price']

    def folder_link(self, obj: Design):
        return get_folder_link_html(obj.folder_id)

    @display(
        description='Папка'
    )
    def get_readonly_fields(self, request, obj=None):
        return ['created_at', 'folder_link'] if obj else []