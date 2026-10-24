from django.contrib.auth.models import Group
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from oauth.models import User
from oauth.services import TEST_MESSAGE_TEXT, send_test_telegram_messages

from ..permissions import IsSuperUser
from ..serializers.users import GroupSerializer, UserSerializer


class UserViewSet(viewsets.ModelViewSet):
    """Staff accounts — superusers only (fine-grained permissions stay in /admin/)."""

    queryset = User.objects.prefetch_related("groups").order_by("name", "phone")
    serializer_class = UserSerializer
    permission_classes = [IsSuperUser]
    search_fields = ["name", "phone"]
    http_method_names = ["get", "post", "patch", "head", "options"]

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
