from unfold.admin import StackedInline
from unfold.decorators import display
from core.utils import get_folder_link_html
from .models import Price



class PriceInline(StackedInline):
    model = Price
    extra = 0
    fk_name = 'metering'
    fields = []
