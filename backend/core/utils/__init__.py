from django.conf import settings

from .filer import copy_folder, create_folder
from .html import *

def media(path):
    return f"{settings.MEDIA_URL}{path}"
