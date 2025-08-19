from unfold.admin import StackedInline
from unfold.decorators import display
from core.utils import get_folder_link_html
from .models import DesignType


class DesignTypeInline(StackedInline):
    model = DesignType
    extra = 0
    exclude = ['folder']
    tab = True

    def folder_link(self, obj: DesignType):
        return get_folder_link_html(obj.folder_id)

    @display(
        description='Папка'
    )
    def get_readonly_fields(self, request, obj=None):
        return ['folder_link'] if obj else []
