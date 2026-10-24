from django.db import transaction
from django.db.models import Count, Q
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from accounting.models import EXPENSE_ORDER_PERMISSION, Expense
from client.models import Client
from core.exceptions import ServiceError
from order.assembly.constants import ASSEMBLY_MANAGER_PERMISSION
from order.assembly.models import Assembly
from order.assembly.services import (
    assemblers,
    mark_assembly_done,
    mark_installing_done,
    ready_for_assembly,
)
from order.constants import ORDER_CHANGE_STATUS_PERMISSION, OrderStatus
from order.detailing.models import Detailing
from order.detailing.services import mark_detailing_done
from order.models import Factory, Order
from order.painter.models import Painter, PainterType
from order.painter.services import assign_painter_type, mark_painter_done, ready_for_painter
from order.rover.models import Rover
from order.rover.services import mark_rover_done
from order.services import (
    advance_order_status,
    create_order,
    send_order_to_assembly,
    send_order_to_detailing,
)

from ..permissions import ModelPermissions, require_perm
from ..serializers.accounting import ExpenseSerializer
from ..serializers.common import UserShortSerializer, can_view_price
from ..serializers.orders import (
    AssemblySerializer,
    DetailingSerializer,
    FactorySerializer,
    OrderCreateSerializer,
    OrderDetailSerializer,
    OrderSerializer,
    OrderUpdateSerializer,
    PainterSerializer,
    PainterTypeSerializer,
    RoverSerializer,
)
from ..utils import apply_period, csv_values, int_param, timeseries, warning_filter


def _bool_param(value):
    if value in ("true", "True", "1"):
        return True
    if value in ("false", "False", "0"):
        return False
    return None


def _history(obj, exclude=()):
    """simple_history records as [{date, user, type, changes:[{field, old, new}]}]."""
    records = list(obj.history.select_related("history_user").order_by("-history_date")[:100])
    labels = {f.name: str(f.verbose_name) for f in obj._meta.fields}
    result = []
    for index, record in enumerate(records):
        previous = records[index + 1] if index + 1 < len(records) else None
        changes = []
        if previous is not None:
            for change in record.diff_against(previous).changes:
                if change.field in exclude:
                    continue
                changes.append(
                    {
                        "field": labels.get(change.field, change.field),
                        "old": None if change.old is None else str(change.old),
                        "new": None if change.new is None else str(change.new),
                    }
                )
        result.append(
            {
                "date": record.history_date,
                "type": {"+": "created", "~": "changed", "-": "deleted"}[record.history_type],
                "user": (
                    UserShortSerializer(record.history_user).data if record.history_user else None
                ),
                "changes": changes,
            }
        )
    return result


class FactoryViewSet(viewsets.ModelViewSet):
    queryset = Factory.objects.all()
    serializer_class = FactorySerializer
    permission_classes = [ModelPermissions]
    pagination_class = None
    search_fields = ["name", "phone"]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def perform_destroy(self, instance):
        if Order.objects.filter(factory=instance).exists():
            raise ServiceError("Zavodda buyurtmalar bor — o'chirib bo'lmaydi")
        instance.delete()


class OrderViewSet(viewsets.ModelViewSet):
    permission_classes = [ModelPermissions]
    search_fields = ["client__fio", "client__phone", "address", "=order_number"]
    ordering_fields = ["order_number", "reception_date", "end_date"]
    ordering = ["-order_number"]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_serializer_class(self):
        if self.action == "list":
            return OrderSerializer
        if self.action == "create":
            return OrderCreateSerializer
        if self.action in ("update", "partial_update"):
            return OrderUpdateSerializer
        return OrderDetailSerializer

    def base_queryset(self):
        params = self.request.query_params
        qs = Order.objects.select_related("client", "factory")
        factory = int_param(params, "factory")
        if factory is not None:
            qs = qs.filter(factory_id=factory)
        warning = params.get("warning")
        if warning:
            qs = warning_filter(qs, warning)
        return apply_period(qs, "reception_date", params)

    def get_queryset(self):
        qs = self.base_queryset()
        statuses = csv_values(self.request.query_params.get("status"))
        if statuses:
            qs = qs.filter(status__in=statuses)
        if self.action != "list":
            qs = qs.select_related(
                "design_type",
                "detailing",
                "rover",
                "painter__type",
                "assembly__user",
            )
        return qs

    def _detail(self, order, code=status.HTTP_200_OK):
        order = Order.objects.select_related(
            "client",
            "factory",
            "design_type",
            "detailing",
            "rover",
            "painter__type",
            "assembly__user",
        ).get(pk=order.pk)
        return Response(
            OrderDetailSerializer(order, context=self.get_serializer_context()).data, status=code
        )

    def create(self, request, *args, **kwargs):
        serializer = OrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        phone = data.pop("client_phone", None)
        fio = (data.pop("client_fio", "") or "").strip()
        if not can_view_price(request):
            for field in ("price", "lost_money", "discount"):
                data.pop(field, None)
        if data.get("price") is None:
            from djmoney import settings as dj_settings
            from djmoney.money import Money

            data["price"] = Money(0, dj_settings.DEFAULT_CURRENCY)
        with transaction.atomic():  # no orphan client if the order is refused
            if phone and not data.get("metering"):
                client = Client.objects.filter(phone=phone).first()
                if client is None:
                    if not fio:
                        raise ServiceError("Yangi mijoz uchun F.I.Sh. kiriting")
                    client = Client.objects.create(phone=phone, fio=fio)
                data["client"] = client
            order = create_order(**data)
        return self._detail(order, status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        order = self.get_object()
        data = request.data.copy() if hasattr(request.data, "copy") else dict(request.data)
        if not can_view_price(request):
            for field in ("price", "lost_money", "discount"):
                if field in data:
                    raise PermissionDenied("Narxni o'zgartirishga ruxsat yo'q.")
        serializer = OrderUpdateSerializer(order, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return self._detail(order)

    @action(detail=True, methods=["post"])
    def detailing(self, request, pk=None):
        require_perm(request.user, "detailing.add_detailing")
        order = self.get_object()
        send_order_to_detailing(order)
        return self._detail(order)

    @action(detail=True, methods=["post"], url_path="next-status")
    def next_status(self, request, pk=None):
        require_perm(request.user, f"order.{ORDER_CHANGE_STATUS_PERMISSION}")
        order = self.get_object()
        advance_order_status(order)
        return self._detail(order)

    @action(detail=True, methods=["post"], url_path="go-to-assembly")
    def go_to_assembly(self, request, pk=None):
        require_perm(request.user, f"assembly.{ASSEMBLY_MANAGER_PERMISSION}")
        order = self.get_object()
        assembly = send_order_to_assembly(order)
        response = self._detail(order)
        response.data["assembly_id"] = assembly.pk
        return response

    @action(detail=True, methods=["get", "post"], serializer_class=ExpenseSerializer)
    def expenses(self, request, pk=None):
        """The order's "Расходы" tab (ExposeInline)."""
        order = self.get_object()
        if request.method == "POST":
            require_perm(request.user, f"accounting.{EXPENSE_ORDER_PERMISSION}")
            data = request.data.copy() if hasattr(request.data, "copy") else dict(request.data)
            # Bound to this order regardless of its status, like the admin inline.
            data.pop("order", None)
            serializer = ExpenseSerializer(data=data)
            serializer.is_valid(raise_exception=True)
            serializer.save(user=request.user, order=order)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        require_perm(request.user, "accounting.view_expense")
        expenses = (
            Expense.objects.filter(order=order)
            .select_related("category", "user", "order__client")
            .order_by("-created_at")
        )
        return Response(ExpenseSerializer(expenses, many=True).data)

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        exclude = () if can_view_price(request) else ("price", "lost_money", "discount")
        return Response(_history(self.get_object(), exclude=exclude))

    @action(detail=False, methods=["get"])
    def stats(self, request):
        """Counts per status (StatusBanner) and per deadline band (WarningBanner)."""
        qs = self.filter_queryset(self.base_queryset())
        counts = {
            row["status"]: row["c"]
            for row in qs.order_by().values("status").annotate(c=Count("pk"))
        }
        return Response(
            {
                "total": qs.count(),
                "by_status": [
                    {"key": value, "count": counts.get(value, 0)} for value in OrderStatus.values
                ],
                "warnings": [
                    {"key": key, "count": warning_filter(qs, key).count()}
                    for key in ("success", "warning", "danger")
                ],
                "timeline": timeseries(qs, "reception_date", request.query_params),
            }
        )


class _ProductionViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Shared plumbing for Detailing / Rover / Painter / Assembly."""

    permission_classes = [ModelPermissions]
    search_fields = ["order__client__fio", "order__client__phone", "=order__order_number"]
    ordering_fields = ["created_at"]
    ordering = ["-created_at"]
    http_method_names = ["get", "post", "patch", "head", "options"]
    done_fields = ("done",)

    def filter_common(self, qs):
        params = self.request.query_params
        for field in self.done_fields:
            value = _bool_param(params.get(field))
            if value is not None:
                qs = qs.filter(**{field: value})
        return apply_period(qs, "created_at", params)

    def _respond(self, obj):
        obj = self.get_queryset().get(pk=obj.pk)
        return Response(self.get_serializer(obj).data)

    @action(detail=False, methods=["get"])
    def stats(self, request):
        qs = self.filter_queryset(self.get_queryset())
        return Response(
            {
                "total": qs.count(),
                "done": qs.filter(done=True).count(),
                "not_done": qs.filter(done=False).count(),
            }
        )


class DetailingViewSet(_ProductionViewSet):
    serializer_class = DetailingSerializer

    def get_queryset(self):
        return self.filter_common(Detailing.objects.select_related("order__client"))

    def update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        # Saving runs the Detailing post_save cascade (Assembly/Painter/Rover squares).
        with transaction.atomic():
            super().update(request, *args, **kwargs)
        return self._respond(self.get_object())

    @action(detail=True, methods=["post"])
    def done(self, request, pk=None):
        require_perm(request.user, "detailing.change_detailing")
        return self._respond(mark_detailing_done(self.get_object()))


class RoverViewSet(_ProductionViewSet):
    serializer_class = RoverSerializer
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        return self.filter_common(Rover.objects.select_related("order__client"))

    @action(detail=True, methods=["post"])
    def done(self, request, pk=None):
        require_perm(request.user, "rover.change_rover")
        return self._respond(mark_rover_done(self.get_object()))


class PainterTypeViewSet(viewsets.ModelViewSet):
    queryset = PainterType.objects.select_related("user").order_by("name")
    serializer_class = PainterTypeSerializer
    permission_classes = [ModelPermissions]
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]


class PainterViewSet(_ProductionViewSet):
    serializer_class = PainterSerializer

    def get_queryset(self):
        # Only orders whose rover is finished (or that have none): painting comes after milling.
        qs = ready_for_painter(Painter.objects.select_related("order__client", "type"))
        # A painter sees only work assigned through their type.
        if not self.request.user.has_perm(f"assembly.{ASSEMBLY_MANAGER_PERMISSION}"):
            qs = qs.filter(type__user=self.request.user)
        return self.filter_common(qs)

    def update(self, request, *args, **kwargs):
        require_perm(request.user, f"assembly.{ASSEMBLY_MANAGER_PERMISSION}")
        painter = self.get_object()
        type_id = request.data.get("type")
        if type_id not in (None, "") and not str(type_id).isdigit():
            raise ServiceError("Molyar turi topilmadi")
        painter_type = PainterType.objects.filter(pk=type_id).first() if type_id else None
        if type_id and painter_type is None:
            raise ServiceError("Bo'yash turi topilmadi")
        assign_painter_type(painter, painter_type)
        return self._respond(painter)

    @action(detail=True, methods=["post"])
    def done(self, request, pk=None):
        require_perm(request.user, "painter.change_painter")
        return self._respond(mark_painter_done(self.get_object()))


class AssemblyViewSet(_ProductionViewSet):
    serializer_class = AssemblySerializer
    done_fields = ("done", "installing_done")

    def get_queryset(self):
        # Only orders past detailing ("Заказ на сырье" and later) are assembly work.
        qs = ready_for_assembly(Assembly.objects.select_related("order__client", "user"))
        # AssemblyAdmin.get_queryset: an assembler sees only their own jobs.
        if not self.request.user.has_perm(f"assembly.{ASSEMBLY_MANAGER_PERMISSION}"):
            qs = qs.filter(user=self.request.user)
        user = int_param(self.request.query_params, "user")
        if user is not None:
            qs = qs.filter(user_id=user)
        return self.filter_common(qs)

    def update(self, request, *args, **kwargs):
        # AssemblyAdmin.has_change_permission: managers only.
        require_perm(request.user, f"assembly.{ASSEMBLY_MANAGER_PERMISSION}")
        assembly = self.get_object()
        user_id = request.data.get("user")
        if user_id not in (None, "") and not str(user_id).isdigit():
            raise ServiceError("Noto'g'ri foydalanuvchi")
        if user_id and not assemblers().filter(pk=user_id).exists():
            raise ServiceError("Bu foydalanuvchi yig'uvchi emas")
        assembly.user_id = user_id or None
        assembly.save(update_fields=["user"])
        return self._respond(assembly)

    @action(detail=True, methods=["post"])
    def done(self, request, pk=None):
        require_perm(request.user, "assembly.change_assembly")
        return self._respond(mark_assembly_done(self.get_object()))

    @action(detail=True, methods=["post"], url_path="installing-done")
    def installing_done(self, request, pk=None):
        require_perm(request.user, "assembly.change_assembly")
        return self._respond(mark_installing_done(self.get_object()))

    @action(detail=False, methods=["get"])
    def assemblers(self, request):
        # Picking an assembler is a manager's job (AssemblyAdmin shows "user" to managers only).
        require_perm(request.user, f"assembly.{ASSEMBLY_MANAGER_PERMISSION}")
        return Response(UserShortSerializer(assemblers().order_by("name"), many=True).data)

    @action(detail=False, methods=["get"])
    def stats(self, request):
        qs = self.filter_queryset(self.get_queryset())
        return Response(
            {
                "total": qs.count(),
                "done": qs.filter(done=True).count(),
                "installing_done": qs.filter(installing_done=True).count(),
                "not_done": qs.filter(Q(done=False) | Q(installing_done=False)).count(),
            }
        )
