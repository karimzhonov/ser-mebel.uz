from django.contrib.auth.models import Group
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from oauth.access import access as section_access
from oauth.access import set_access
from oauth.models import User
from oauth.services import TEST_MESSAGE_TEXT, delete_user, send_test_telegram_messages

from ..permissions import IsSuperUser
from ..serializers.users import GroupSerializer, UserSerializer


class UserViewSet(viewsets.ModelViewSet):
    """Staff accounts — superusers only (fine-grained permissions stay in /admin/)."""

    queryset = User.objects.prefetch_related("groups").order_by("name", "phone")
    serializer_class = UserSerializer
    permission_classes = [IsSuperUser]
    search_fields = ["name", "phone"]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def perform_destroy(self, instance):
        delete_user(self.request.user, instance)

    @action(detail=True, methods=["get", "post"])
    def access(self, request, pk=None):
        """Section levels (none / view / edit). POST {levels: {section: level}} sets
        only the sections sent."""
        user = self.get_object()
        if request.method == "POST":
            levels = request.data.get("levels")
            if not isinstance(levels, dict):
                raise ValidationError({"levels": "Bo'limlar ro'yxati kerak"})
            return Response(set_access(user, levels))
        return Response(section_access(user))

    @action(detail=True, methods=["post"], url_path="test-message")
    def test_message(self, request, pk=None):
        sent, without_telegram, failed = send_test_telegram_messages([self.get_object()])
        return Response(
            {
                "sent": sent,
                "without_telegram": without_telegram,
                "failed": failed,
                "text": TEST_MESSAGE_TEXT,
            }
        )


class GroupViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = Group.objects.order_by("name")
    serializer_class = GroupSerializer
    permission_classes = [IsSuperUser]
    pagination_class = None
