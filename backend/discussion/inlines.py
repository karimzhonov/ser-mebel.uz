from unfold.admin import GenericTabularInline
from django.contrib.contenttypes.models import ContentType
from .models import DiscussionMessage


class DiscussionInline(GenericTabularInline):
    model = DiscussionMessage
    extra = 0
    exclude = ['author']
    can_delete = False

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(content_type=ContentType.objects.get_for_model(self.parent_model))

    def save_model(self, request, obj: DiscussionMessage, form, change):
        obj.content_type = ContentType.objects.get_for_model(self.parent_model)
        obj.author = request.user
        super().save_model(request, obj, form, change)
