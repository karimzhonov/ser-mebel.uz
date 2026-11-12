from django.db import transaction
from django.db.models import Count, Exists, Min, OuterRef, Prefetch, ProtectedError, Q, Subquery
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.response import Response

from accounting.text import today as accounting_today
from client.models import Client
from core.exceptions import ServiceError
from core.geo import UNSET
from oauth.models import User
from order.assembly.constants import ASSEMBLY_MANAGER_PERMISSION
from order.assembly.models import Assembly
from order.assembly.services import (
    active_assemblers,
    assign_assembler,
    confirm_assembly,
    mark_assembly_done,
    mark_installing_done,
    ready_for_assembly,
    set_assembly_due,
)
from order.constants import (
    ORDER_CHANGE_STATUS_PERMISSION,
    ORDER_VIEW_PRICE_PERMISSION,
    OrderStatus,
)
from order.detailing.models import Detailing
from order.detailing.services import mark_detailing_done, set_detailing_due
from order.models import Factory, Order
from order.painter.models import Painter, PainterPart, PainterType
from order.painter.services import (
    assign_whole_job,
    mark_painter_done,
    mark_part_done,
    ready_for_painter,
    set_painter_due,
    set_painter_parts,
    set_part_due,
)
from order.rover.models import Rover
from order.rover.services import confirm_rover, set_rover_due, submit_rover
from order.services import (
    advance_order_status,
    can_send_to_assembly,
    create_order,
    send_order_to_assembly,
    send_order_to_detailing,
    set_order_location,
    underpaid_orders,
)
from order.visibility import sees_full_order

from ..permissions import ModelPermissions, require_perm
from ..serializers.common import LocationSetSerializer, UserShortSerializer, can_view_price
from ..serializers.orders import (
    AssemblyAssignSerializer,
    AssemblyDueSerializer,
    AssemblyFinishSerializer,
    AssemblySerializer,
    DetailingDueSerializer,
    DetailingSerializer,
    FactorySerializer,
    OrderCreateSerializer,
    OrderDetailSerializer,
    OrderSerializer,
    OrderUpdateSerializer,
    PainterAssignSerializer,
    PainterDoneSerializer,
    PainterDueSerializer,
    PainterPartsSerializer,
    PainterSerializer,
    PainterTypeSerializer,
    RoverDoneSerializer,
    RoverDueSerializer,
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
        if params.get("underpaid") == "1":
            # «65% dan kam to'lagan»: money, so only for who may see order prices
            require_perm(self.request.user, f"order.{ORDER_VIEW_PRICE_PERMISSION}")
            qs = underpaid_orders(qs)
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
                "painter",
                "assembly__user",
            ).prefetch_related("painter__parts__type")
        return qs

    def _detail(self, order, code=status.HTTP_200_OK):
        order = (
            Order.objects.select_related(
                "client",
                "factory",
                "design_type",
                "detailing",
                "rover",
                "painter",
                "assembly__user",
            )
            .prefetch_related("painter__parts__type")
            .get(pk=order.pk)
        )
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
        # owner's rule: the advance entered here waits for the boss («Avans tasdiqlash»);
        # it reaches the order's «Полученная сумма» only once he confirms the money
        advance = data.pop("lost_money", None)
        with transaction.atomic():  # no orphan client if the order is refused
            if phone and not data.get("metering"):
                client = Client.objects.filter(phone=phone).first()
                if client is None:
                    if not fio:
                        raise ServiceError("Yangi mijoz uchun F.I.Sh. kiriting")
                    client = Client.objects.create(phone=phone, fio=fio)
                data["client"] = client
            order = create_order(author=request.user, **data)
            if advance is not None:
                from accounting.services import advance_open

                advance_open(order, advance.amount, str(advance.currency), by_user=request.user)
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
    def location(self, request, pk=None):
        """Attach / clear the order's map location: {location, address?}."""
        require_perm(request.user, "order.change_order")
        order = self.get_object()
        body = LocationSetSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        d = body.validated_data
        set_order_location(
            order,
            point=d["point"],
            link=d["link"],
            address=d["address"] if "address" in d else UNSET,
            by=request.user,
        )
        response = self._detail(order)
        response.data = {**response.data, "short": d["short"]}
        return response

    @action(detail=True, methods=["post"], serializer_class=DetailingDueSerializer)
    def detailing(self, request, pk=None):
        """Send to detailing with its deadline: {due_at}."""
        require_perm(request.user, "detailing.add_detailing")
        order = self.get_object()
        body = DetailingDueSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        send_order_to_detailing(order, due_at=body.validated_data["due_at"])
        return self._detail(order)

    @action(detail=True, methods=["post"], url_path="next-status")
    def next_status(self, request, pk=None):
        require_perm(request.user, f"order.{ORDER_CHANGE_STATUS_PERMISSION}")
        order = self.get_object()
        advance_order_status(order)
        return self._detail(order)

    @action(detail=True, methods=["post"], url_path="go-to-assembly")
    def go_to_assembly(self, request, pk=None):
        if not can_send_to_assembly(request.user):
            raise PermissionDenied("Bu amal uchun huquq yetarli emas.")
        order = self.get_object()
        assembly = send_order_to_assembly(order)
        response = self._detail(order)
        response.data["assembly_id"] = assembly.pk
        return response

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
                # «65% dan kam to'lagan» tile: money, so only with the price permission
                "underpaid": (
                    underpaid_orders(qs).count()
                    if request.user.has_perm(f"order.{ORDER_VIEW_PRICE_PERMISSION}")
                    else None
                ),
            }
        )


def _design_folder_subquery():
    """The order's «Дизайн» folder: under the order folder (after the order is made), else
    under the metering folder."""
    from django.db.models.functions import Coalesce
    from filer.models import Folder

    def under(field):
        return Subquery(
            Folder.objects.filter(parent_id=OuterRef(field), name="Дизайн")
            .order_by("pk")
            .values("pk")[:1]
        )

    return Coalesce(under("order__folder_id"), under("order__metering__folder_id"))


class _NoPhoneSearchFilter(SearchFilter):
    """Restricted viewers (see `order.visibility`) must not find a job by the client's phone."""

    def get_search_fields(self, view, request):
        fields = super().get_search_fields(view, request)
        if sees_full_order(request.user):
            return fields
        return [f for f in fields if "phone" not in f]


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

    @action(detail=True, methods=["post"], serializer_class=DetailingDueSerializer)
    def due(self, request, pk=None):
        """Move the deadline (whoever may send to detailing): {due_at}."""
        require_perm(request.user, "detailing.add_detailing")
        body = DetailingDueSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return self._respond(
            set_detailing_due(self.get_object(), due_at=body.validated_data["due_at"])
        )


class RoverViewSet(_ProductionViewSet):
    serializer_class = RoverSerializer
    filter_backends = [DjangoFilterBackend, _NoPhoneSearchFilter, OrderingFilter]
    http_method_names = ["get", "post", "head", "options"]
    ordering_fields = ["created_at", "due_date"]

    def _respond(self, obj):
        # always the full card, whatever serializer the action documents for its input
        obj = self.get_queryset().get(pk=obj.pk)
        return Response(RoverSerializer(obj, context=self.get_serializer_context()).data)

    def get_queryset(self):
        design = _design_folder_subquery()
        qs = Rover.objects.select_related(
            "order__client", "order__metering", "submitted_by", "checked_by", "due_set_by"
        ).annotate(design_folder_pk=design)
        qs = self.filter_common(qs)
        if _bool_param(self.request.query_params.get("overdue")):
            qs = qs.filter(done=False, submitted_at__isnull=True, due_date__lt=accounting_today())
        state = self.request.query_params.get("state")
        if state == "new":
            qs = qs.filter(done=False, submitted_at__isnull=True)
        elif state == "checking":
            qs = qs.filter(done=False, submitted_at__isnull=False)
        elif state == "done":
            qs = qs.filter(done=True)
        return qs

    @action(detail=False, methods=["get"])
    def stats(self, request):
        qs = self.filter_queryset(self.get_queryset())
        return Response(
            {
                "total": qs.count(),
                "done": qs.filter(done=True).count(),
                "not_done": qs.filter(done=False, submitted_at__isnull=True).count(),
                "checking": qs.filter(done=False, submitted_at__isnull=False).count(),
            }
        )

    @action(detail=True, methods=["post"])
    def done(self, request, pk=None):
        """The worker's «Bajarildi»: {price: {amount, currency}, note} - the actual amount and what was done;
        the job then waits for a checker."""
        require_perm(request.user, "rover.change_rover")
        body = RoverDoneSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return self._respond(
            submit_rover(
                self.get_object(),
                by=request.user,
                price=body.validated_data["price"],
                note=body.validated_data["note"],
            )
        )

    @action(detail=True, methods=["post"], serializer_class=RoverDueSerializer)
    def due(self, request, pk=None):
        """The production head's deadline: {due_date: "YYYY-MM-DD"}."""
        require_perm(request.user, "oauth.user_production_head")
        body = RoverDueSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return self._respond(
            set_rover_due(
                self.get_object(), by=request.user, due_date=body.validated_data["due_date"]
            )
        )

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        require_perm(request.user, "oauth.user_rover_checker")
        return self._respond(confirm_rover(self.get_object(), by=request.user))


class PainterTypeViewSet(viewsets.ModelViewSet):
    queryset = PainterType.objects.select_related("user").order_by("name")
    serializer_class = PainterTypeSerializer
    permission_classes = [ModelPermissions]
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def perform_destroy(self, instance):
        try:
            instance.delete()
        except ProtectedError:
            raise ServiceError("Bu jamoada Molyar ishlari bor — o'chirib bo'lmaydi")


class _PainterOrdering(OrderingFilter):
    """`ordering=due_date` sorts by the earliest open part's deadline (`next_due`)."""

    def get_ordering(self, request, queryset, view):
        ordering = super().get_ordering(request, queryset, view)
        if not ordering:
            return ordering
        return [t.replace("due_date", "next_due") for t in ordering]


class PainterViewSet(_ProductionViewSet):
    serializer_class = PainterSerializer
    filter_backends = [DjangoFilterBackend, _NoPhoneSearchFilter, _PainterOrdering]
    # `due_date` = the earliest open part's deadline (the job column is deprecated)
    ordering_fields = ["created_at", "due_date"]

    def _respond(self, obj):
        # always the full card, whatever serializer the action documents for its input
        obj = self.get_queryset().get(pk=obj.pk)
        return Response(PainterSerializer(obj, context=self.get_serializer_context()).data)

    def _is_worker(self):
        user = self.request.user
        return not (
            user.has_perm(f"assembly.{ASSEMBLY_MANAGER_PERMISSION}")
            or user.has_perm("oauth.user_production_head")
        )

    def get_queryset(self):
        # Only orders whose rover is finished (or that have none): painting comes after milling.
        design = _design_folder_subquery()
        qs = ready_for_painter(
            Painter.objects.select_related("order__client", "order__metering", "done_by")
            .prefetch_related(
                Prefetch(
                    "parts",
                    queryset=PainterPart.objects.select_related(
                        "type__user", "done_by", "due_set_by"
                    ).order_by("pk"),
                )
            )
            .annotate(
                design_folder_pk=design,
                next_due=Min("parts__due_date", filter=Q(parts__done=False)),
            )
        )
        # Managers and production heads see every job; a painter only the jobs where one of
        # their parts is (Exists: a job with two of their parts is still one row).
        user = self.request.user
        if self._is_worker():
            qs = qs.filter(
                Exists(PainterPart.objects.filter(painter=OuterRef("pk"), type__user=user))
            )
        qs = self.filter_common(qs)
        if _bool_param(self.request.query_params.get("overdue")):
            own = Q(type__user=user) if self._is_worker() else Q()
            qs = qs.filter(
                Exists(
                    PainterPart.objects.filter(
                        own, painter=OuterRef("pk"), done=False, due_date__lt=accounting_today()
                    )
                )
            )
        return qs

    def filter_common(self, qs):
        # a worker's done/not done is about their own parts, a head's about the job
        done = _bool_param(self.request.query_params.get("done"))
        if done is not None and self._is_worker():
            open_own = Exists(
                PainterPart.objects.filter(
                    painter=OuterRef("pk"), type__user=self.request.user, done=False
                )
            )
            qs = qs.filter(~open_own if done else open_own)
            return apply_period(qs, "created_at", self.request.query_params)
        return super().filter_common(qs)

    @action(detail=False, methods=["get"])
    def stats(self, request):
        if not self._is_worker():
            return super().stats(request)
        qs = self.filter_queryset(self.get_queryset())
        open_own = Exists(
            PainterPart.objects.filter(painter=OuterRef("pk"), type__user=request.user, done=False)
        )
        return Response(
            {
                "total": qs.count(),
                "done": qs.filter(~open_own).count(),
                "not_done": qs.filter(open_own).count(),
            }
        )

    def _assign(self, request, type_id):
        require_perm(request.user, "oauth.user_production_head")
        painter = self.get_object()
        painter_type = None
        if type_id not in (None, ""):
            painter_type = PainterType.objects.select_related("user").filter(pk=type_id).first()
            if painter_type is None:
                raise ServiceError("Bo'yash turi topilmadi")
        assign_whole_job(painter, painter_type, by=request.user)
        return self._respond(painter)

    def update(self, request, *args, **kwargs):
        # kept for compatibility: PATCH {type} == POST assign/
        type_id = request.data.get("type")
        if type_id not in (None, "") and not str(type_id).isdigit():
            raise ServiceError("Molyar turi topilmadi")
        return self._assign(request, type_id)

    @action(detail=True, methods=["post"], serializer_class=PainterAssignSerializer)
    def assign(self, request, pk=None):
        """The production head gives the whole job to one team (painter type): {type: id|null}."""
        body = PainterAssignSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return self._assign(request, body.validated_data["type"])

    @action(detail=True, methods=["post"], serializer_class=PainterPartsSerializer)
    def parts(self, request, pk=None):
        """The production head splits the job between teams by m²:
        {parts: [{id?, type, square}]} = the desired OPEN parts (done parts stay)."""
        require_perm(request.user, "oauth.user_production_head")
        body = PainterPartsSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        painter = self.get_object()
        rows = body.validated_data["parts"]
        types = {
            t.pk: t
            for t in PainterType.objects.select_related("user").filter(
                pk__in=[r["type"] for r in rows]
            )
        }
        clean = []
        for r in rows:
            if r["type"] not in types:
                raise ServiceError("Bo'yash turi topilmadi", field="parts")
            clean.append({"id": r.get("id"), "type": types[r["type"]], "square": r["square"]})
        set_painter_parts(painter, clean, by=request.user)
        return self._respond(painter)

    def _part_of(self, painter, part_id):
        part = painter.parts.select_related("type__user").filter(pk=part_id).first()
        if part is None:
            raise ServiceError("Qism topilmadi", field="part")
        return part

    @action(detail=True, methods=["post"], serializer_class=PainterDoneSerializer)
    def done(self, request, pk=None):
        """The painter's «Bajarildi»: {note, part?} - what was done on the part; the service
        checks who may."""
        body = PainterDoneSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        painter = self.get_object()
        note = body.validated_data["note"]
        part_id = body.validated_data.get("part")
        if part_id is not None:
            mark_part_done(self._part_of(painter, part_id), by=request.user, note=note)
        else:
            mark_painter_done(painter, by=request.user, note=note)
        return self._respond(painter)

    @action(detail=True, methods=["post"], serializer_class=PainterDueSerializer)
    def due(self, request, pk=None):
        """The production head's deadline: {due_date: "YYYY-MM-DD", part?}."""
        require_perm(request.user, "oauth.user_production_head")
        body = PainterDueSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        painter = self.get_object()
        due_date = body.validated_data["due_date"]
        part_id = body.validated_data.get("part")
        if part_id is not None:
            set_part_due(self._part_of(painter, part_id), by=request.user, due_date=due_date)
        else:
            set_painter_due(painter, by=request.user, due_date=due_date)
        return self._respond(painter)


class AssemblyViewSet(_ProductionViewSet):
    serializer_class = AssemblySerializer
    done_fields = ("done", "installing_done")
    ordering_fields = ["created_at", "due_date"]

    def _respond(self, obj):
        # always the full card, whatever serializer the action documents for its input
        obj = self.get_queryset().get(pk=obj.pk)
        return Response(AssemblySerializer(obj, context=self.get_serializer_context()).data)

    def get_queryset(self):
        # Only orders past detailing ("Заказ на сырье" and later) are assembly work.
        qs = ready_for_assembly(
            Assembly.objects.select_related(
                "order__client", "user", "finished_by", "confirmed_by", "due_set_by"
            )
        )
        # Managers and production heads see every job; an assembler only their own.
        user = self.request.user
        if not (
            user.has_perm(f"assembly.{ASSEMBLY_MANAGER_PERMISSION}")
            or user.has_perm("oauth.user_production_head")
        ):
            qs = qs.filter(user=user)
        user_id = int_param(self.request.query_params, "user")
        if user_id is not None:
            qs = qs.filter(user_id=user_id)
        qs = self.filter_common(qs)
        if _bool_param(self.request.query_params.get("overdue")):
            qs = qs.filter(
                installing_done=False,
                finished_at__isnull=True,
                due_date__lt=accounting_today(),
            )
        if self.request.query_params.get("state") == "checking":
            qs = qs.filter(finished_at__isnull=False, installing_done=False)
        return qs

    def _assign(self, request, user_id):
        require_perm(request.user, "oauth.user_production_head")
        assembly = self.get_object()
        assembler = None
        if user_id not in (None, ""):
            assembler = User.objects.filter(pk=user_id).first()
            if assembler is None:
                raise ServiceError("Noto'g'ri foydalanuvchi", field="user")
        assign_assembler(assembly, assembler, by=request.user)
        return self._respond(assembly)

    def update(self, request, *args, **kwargs):
        # legacy PATCH {user}: also needs assembly.change_assembly (ModelPermissions), so a
        # head with view-only rights uses POST assign/ (what the panel calls)
        user_id = request.data.get("user")
        if user_id not in (None, "") and not str(user_id).isdigit():
            raise ServiceError("Noto'g'ri foydalanuvchi", field="user")
        return self._assign(request, user_id)

    @action(detail=True, methods=["post"], serializer_class=AssemblyAssignSerializer)
    def assign(self, request, pk=None):
        """The production head picks the assembler (the team): {user: id|null}."""
        body = AssemblyAssignSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return self._assign(request, body.validated_data["user"])

    @action(detail=True, methods=["post"])
    def done(self, request, pk=None):
        """«Yig'ildi»: the assembler or an assembly manager (the service checks who)."""
        return self._respond(mark_assembly_done(self.get_object(), by=request.user))

    @action(
        detail=True,
        methods=["post"],
        url_path="installing-done",
        serializer_class=AssemblyFinishSerializer,
    )
    def installing_done(self, request, pk=None):
        """«O'rnatildi»: {note} - what was done; the job waits for the head's «Tayyor»."""
        body = AssemblyFinishSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return self._respond(
            mark_installing_done(
                self.get_object(), by=request.user, note=body.validated_data["note"]
            )
        )

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        """The production head's «Tayyor»: the job is closed and the order becomes Готов."""
        require_perm(request.user, "oauth.user_production_head")
        return self._respond(confirm_assembly(self.get_object(), by=request.user))

    @action(detail=True, methods=["post"], serializer_class=AssemblyDueSerializer)
    def due(self, request, pk=None):
        """The production head's deadline: {due_date: "YYYY-MM-DD"}."""
        require_perm(request.user, "oauth.user_production_head")
        body = AssemblyDueSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return self._respond(
            set_assembly_due(
                self.get_object(), by=request.user, due_date=body.validated_data["due_date"]
            )
        )

    @action(detail=False, methods=["get"])
    def assemblers(self, request):
        # Picking an assembler is the production head's job (managers still see the list).
        user = request.user
        if not (
            user.has_perm(f"assembly.{ASSEMBLY_MANAGER_PERMISSION}")
            or user.has_perm("oauth.user_production_head")
        ):
            raise PermissionDenied("Bu amal uchun huquq yetarli emas.")
        return Response(UserShortSerializer(active_assemblers().order_by("name"), many=True).data)

    @action(detail=False, methods=["get"])
    def stats(self, request):
        qs = self.filter_queryset(self.get_queryset())
        return Response(
            {
                "total": qs.count(),
                "done": qs.filter(done=True).count(),
                "checking": qs.filter(finished_at__isnull=False, installing_done=False).count(),
                "installing_done": qs.filter(installing_done=True).count(),
                # «Ishda» excludes jobs waiting for the head's «Tayyor» (own tile above)
                "not_done": qs.filter(installing_done=False, finished_at__isnull=True).count(),
            }
        )
