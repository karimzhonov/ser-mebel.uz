from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models import Count
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from oauth.access import access as section_access
from oauth.access import group_access, set_access, set_group_access
from oauth.models import User
from oauth.services import (
    TEST_MESSAGE_TEXT,
    add_group_member,
    create_group,
    delete_group,
    delete_user,
    group_members,
    merge_group,
    merge_plan,
    merge_preview,
    remove_group_member,
    rename_group,
    send_test_telegram_messages,
)

from ..permissions import IsSuperUser
from ..serializers.users import GroupMemberSerializer, GroupSerializer, UserSerializer


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


class GroupViewSet(viewsets.GenericViewSet):
    """Groups are the roles (Operator, Dizayner, Bosh menejer ...): CRUD, the same
    section levels / yes-no flags as a person (`access/`), and the members."""

    queryset = Group.objects.annotate(n_members=Count("user")).order_by("name")
    serializer_class = GroupSerializer
    permission_classes = [IsSuperUser]
    pagination_class = None

    def _out(self, group):
        return Response(self.get_serializer(self.get_queryset().get(pk=group.pk)).data)

    def list(self, request):
        return Response(self.get_serializer(self.get_queryset(), many=True).data)

    def retrieve(self, request, pk=None):
        return Response(self.get_serializer(self.get_object()).data)

    def create(self, request):
        group = create_group(request.data.get("name"))
        resp = self._out(group)
        resp.status_code = 201
        return resp

    def partial_update(self, request, pk=None):
        return self._out(rename_group(self.get_object(), request.data.get("name")))

    update = partial_update

    def destroy(self, request, pk=None):
        delete_group(self.get_object())
        return Response(status=204)

    @action(detail=False, methods=["get"], url_path="merge-plan")
    def merge_plan(self, request):
        """Review screen data: old groups and where each should go (changes nothing)."""
        return Response(merge_plan())

    def _target(self, value):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationError({"target": "Lavozimni tanlang"})
        try:
            return Group.objects.get(pk=value)
        except Group.DoesNotExist:
            raise ValidationError({"target": "Lavozim topilmadi"})

    @action(detail=True, methods=["get"], url_path="merge-preview")
    def merge_preview(self, request, pk=None):
        """?target=<id> (omit for «shaxsiy huquq»): who moves and what is added."""
        raw = request.query_params.get("target")
        target = None
        if raw not in (None, "", "personal"):
            try:
                target = self._target(int(raw))
            except ValueError:
                raise ValidationError({"target": "Lavozimni tanlang"})
        return Response(merge_preview(self.get_object(), target))

    @action(detail=True, methods=["post"], url_path="merge-into")
    def merge_into(self, request, pk=None):
        """{target: id} or {to_personal: true}; atomic, deletes the old group."""
        source = self.get_object()
        if request.data.get("to_personal") is True:
            return Response(merge_group(source, None))
        return Response(merge_group(source, self._target(request.data.get("target"))))

    @action(detail=True, methods=["get", "post"])
    def access(self, request, pk=None):
        """Section levels of the role; POST {levels: {section: level}} like a person's."""
        group = self.get_object()
        if request.method == "POST":
            levels = request.data.get("levels")
            if not isinstance(levels, dict):
                raise ValidationError({"levels": "Bo'limlar ro'yxati kerak"})
            return Response(set_group_access(group, levels))
        return Response(group_access(group))

    @action(detail=True, methods=["get", "post"])
    def members(self, request, pk=None):
        """GET: the people in the role. POST {add?: [user ids], remove?: [user ids]}."""
        group = self.get_object()
        if request.method == "POST":
            lists = {}
            for key in ("add", "remove"):
                ids = request.data.get(key) or []
                if not isinstance(ids, list) or not all(
                    isinstance(i, int) and not isinstance(i, bool) for i in ids
                ):
                    raise ValidationError({key: "Xodimlar ro'yxati kerak"})
                users = list(User.objects.filter(pk__in=ids))
                if len(users) != len(set(ids)):
                    raise ValidationError({key: "Xodim topilmadi"})
                lists[key] = users
            with transaction.atomic():
                for user in lists["add"]:
                    add_group_member(group, user)
                for user in lists["remove"]:
                    remove_group_member(group, user)
        return Response(GroupMemberSerializer(group_members(group), many=True).data)
