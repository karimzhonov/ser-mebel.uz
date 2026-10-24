from django.db import transaction
from django.db.models import Count, Prefetch
from django.shortcuts import get_object_or_404
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from call_center.models import Invoice
from client.models import Client
from core.exceptions import ServiceError
from metering.constants import MeteringStatus
from metering.design.models import Design, DesignType
from metering.design.services import add_design_type, mark_design_done
from metering.models import Metering
from metering.price.excel import download_inlines_excel
from metering.price.models import Calculate, Inventory, InventoryType, ObjectType, Price
from metering.price.services import delete_calculation, mark_price_done, save_calculation
from metering.services import (
    create_metering,
    mark_metering_done,
    mark_metering_dont_need,
    mark_metering_other_day,
    metering_is_editable,
    start_design,
    start_price,
)
from oauth.constants import METERING_PERMISSION

from ..permissions import ModelPermissions, require_perm
from ..serializers.metering import (
    CalculationInputSerializer,
    DesignSerializer,
    DesignTypeSerializer,
    InventorySerializer,
    InventoryTypeSerializer,
    MeteringCreateSerializer,
    MeteringDetailSerializer,
    MeteringSerializer,
    MeteringUpdateSerializer,
    ObjectTypeSerializer,
    OtherDaySerializer,
    PriceDetailSerializer,
    PriceSerializer,
)
from ..utils import apply_period, csv_values, int_param, timeseries


def _bool_param(value):
    if value in ("true", "True", "1"):
        return True
    if value in ("false", "False", "0"):
        return False
    return None


class MeteringViewSet(viewsets.ModelViewSet):
    permission_classes = [ModelPermissions]
    search_fields = ["client__fio", "client__phone", "address"]
    ordering_fields = ["date_time", "create_date"]
    ordering = ["-date_time"]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return MeteringDetailSerializer
        if self.action in ("update", "partial_update"):
            return MeteringUpdateSerializer
        return MeteringSerializer

    def base_queryset(self):
        qs = Metering.objects.select_related("client", "design", "price", "order")
        return apply_period(qs, "create_date", self.request.query_params)

    def get_queryset(self):
        qs = self.base_queryset()
        statuses = csv_values(self.request.query_params.get("status"))
        if statuses:
            qs = qs.filter(status__in=statuses)
        return qs

    def _detail(self, metering, code=status.HTTP_200_OK):
        metering = self.base_queryset().get(pk=metering.pk)
        return Response(
            MeteringDetailSerializer(metering, context=self.get_serializer_context()).data,
            status=code,
        )

    def create(self, request, *args, **kwargs):
        serializer = MeteringCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        phone = data.pop("client_phone")
        fio = (data.pop("client_fio", "") or "").strip()
        invoice_id = data.pop("invoice", None)
        invoice = get_object_or_404(Invoice, pk=invoice_id) if invoice_id else None
        with transaction.atomic():  # no orphan client if the metering is refused
            client = Client.objects.filter(phone=phone).first()
            if client is None:
                if not fio:
                    raise ServiceError("Янги мижоз учун ФИО киритинг")
                client = Client.objects.create(phone=phone, fio=fio)
            metering = create_metering(client=client, invoice=invoice, **data)
        return self._detail(metering, status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        metering = self.get_object()
        if not metering_is_editable(metering):
            raise PermissionDenied("Архивдаги замерни таҳрирлаб бўлмайди.")
        kwargs["partial"] = True
        super().update(request, *args, **kwargs)
        return self._detail(metering)

    @action(detail=True, methods=["post"], url_path="dont-need")
    def dont_need(self, request, pk=None):
        require_perm(request.user, "metering.change_metering")
        return self._detail(mark_metering_dont_need(self.get_object()))

    @action(
        detail=True, methods=["post"], url_path="other-day", serializer_class=OtherDaySerializer
    )
    def other_day(self, request, pk=None):
        require_perm(request.user, "metering.change_metering")
        serializer = OtherDaySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        metering = mark_metering_other_day(
            self.get_object(), serializer.validated_data.get("date_time")
        )
        return self._detail(metering)

    @action(detail=True, methods=["post"], url_path="metering-done")
    def metering_done(self, request, pk=None):
        require_perm(request.user, f"oauth.{METERING_PERMISSION}")
        return self._detail(mark_metering_done(self.get_object()))

    @action(detail=True, methods=["post"], url_path="create-design")
    def create_design(self, request, pk=None):
        require_perm(request.user, "design.add_design")
        metering = self.get_object()
        start_design(metering)
        return self._detail(metering)

    @action(detail=True, methods=["post"], url_path="create-price")
    def create_price(self, request, pk=None):
        require_perm(request.user, "price.add_price")
        metering = self.get_object()
        start_price(metering)
        return self._detail(metering)

    @action(detail=False, methods=["get"])
    def stats(self, request):
        """Counts per status (the admin MeteringStatusBanner) + the line chart."""
        qs = self.filter_queryset(self.base_queryset())
        counts = {
            row["status"]: row["c"]
            for row in qs.order_by().values("status").annotate(c=Count("pk"))
        }
        return Response(
            {
                "total": qs.count(),
                "by_status": [
                    {"key": value, "count": counts.get(value, 0)} for value in MeteringStatus.values
                ],
                "timeline": timeseries(qs, "create_date", request.query_params),
            }
        )


class DesignViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Designs are only created from a metering (MeteringViewSet.create_design)."""

    serializer_class = DesignSerializer
    permission_classes = [ModelPermissions]
    search_fields = ["metering__client__fio", "metering__client__phone"]
    ordering_fields = ["created_at"]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = Design.objects.select_related("metering__client", "metering__order").prefetch_related(
            "designtype_set"
        )
        params = self.request.query_params
        for field in ("done", "confirm"):
            value = _bool_param(params.get(field))
            if value is not None:
                qs = qs.filter(**{field: value})
        return apply_period(qs, "created_at", params)

    @action(detail=True, methods=["post"])
    def done(self, request, pk=None):
        require_perm(request.user, "design.change_design")
        design = mark_design_done(self.get_object())
        return Response(self.get_serializer(design).data)

    @action(detail=True, methods=["post"], serializer_class=DesignTypeSerializer)
    def types(self, request, pk=None):
        """Add one more design variant (the admin's DesignType inline)."""
        require_perm(request.user, "design.add_designtype")
        design = self.get_object()
        serializer = DesignTypeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        add_design_type(design, serializer.validated_data["name"])
        design = self.get_queryset().get(pk=design.pk)
        return Response(DesignSerializer(design, context=self.get_serializer_context()).data)


class DesignTypeViewSet(mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    queryset = DesignType.objects.all()
    serializer_class = DesignTypeSerializer
    permission_classes = [ModelPermissions]
    http_method_names = ["patch", "delete", "options"]

    def perform_destroy(self, instance):
        from order.models import Order

        if Order.objects.filter(design_type=instance).exists():
            raise ServiceError("Бу вариант заказда ишлатилган — ўчириб бўлмайди")
        instance.delete()


class PriceViewSet(viewsets.ModelViewSet):
    permission_classes = [ModelPermissions]
    search_fields = ["metering__client__fio", "metering__client__phone", "desc"]
    ordering_fields = ["created_at"]
    ordering = ["-created_at"]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_serializer_class(self):
        if self.action in ("retrieve", "create", "partial_update", "update"):
            return PriceDetailSerializer
        return PriceSerializer

    def get_queryset(self):
        qs = Price.objects.select_related("metering__client", "metering__order")
        params = self.request.query_params
        done = _bool_param(params.get("done"))
        if done is not None:
            qs = qs.filter(done=done)
        has_metering = _bool_param(params.get("has_metering"))
        if has_metering is not None:
            qs = qs.filter(metering__isnull=not has_metering)
        return apply_period(qs, "created_at", params)

    def _detail(self, price):
        price = self.get_queryset().get(pk=price.pk)
        return Response(PriceDetailSerializer(price, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"])
    def done(self, request, pk=None):
        require_perm(request.user, "price.change_price")
        return self._detail(mark_price_done(self.get_object()))

    @action(detail=True, methods=["get"])
    def excel(self, request, pk=None):
        price = self.get_object()
        return download_inlines_excel(None, request, price.pk)

    @action(
        detail=True,
        methods=["post"],
        url_path="calculations",
        serializer_class=CalculationInputSerializer,
    )
    def add_calculation(self, request, pk=None):
        require_perm(request.user, "price.change_price", "price.add_calculate")
        price = self.get_object()
        serializer = CalculationInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        save_calculation(
            price=price,
            object_type=data["object_type"],
            name=data["name"],
            count=data["count"],
            items=data.get("items", []),
        )
        return self._detail(price)

    @action(
        detail=True,
        methods=["patch", "delete"],
        url_path=r"calculations/(?P<calc_id>\d+)",
        serializer_class=CalculationInputSerializer,
    )
    def calculation(self, request, pk=None, calc_id=None):
        require_perm(request.user, "price.change_price")
        price = self.get_object()
        calc = get_object_or_404(Calculate, pk=calc_id, price=price)
        require_perm(
            request.user,
            "price.delete_calculate" if request.method == "DELETE" else "price.change_calculate",
        )
        if request.method == "DELETE":
            delete_calculation(calc)
            return self._detail(price)
        serializer = CalculationInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        save_calculation(
            price=price,
            object_type=data["object_type"],
            name=data["name"],
            count=data["count"],
            items=data.get("items", []),
            calculation=calc,
        )
        return self._detail(price)


class ObjectTypeViewSet(viewsets.ModelViewSet):
    queryset = ObjectType.objects.order_by("pk")
    serializer_class = ObjectTypeSerializer
    permission_classes = [ModelPermissions]
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]


class InventoryTypeViewSet(viewsets.ModelViewSet):
    serializer_class = InventoryTypeSerializer
    permission_classes = [ModelPermissions]
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = InventoryType.objects.prefetch_related(
            Prefetch("inventory_set", queryset=Inventory.objects.order_by("name"))
        ).order_by("ordering", "pk")
        obj = int_param(self.request.query_params, "obj")
        if obj is not None:
            qs = qs.filter(obj_id=obj)
        return qs


class InventoryViewSet(viewsets.ModelViewSet):
    serializer_class = InventorySerializer
    permission_classes = [ModelPermissions]
    pagination_class = None
    search_fields = ["name"]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = Inventory.objects.select_related("type").order_by("name")
        type_id = int_param(self.request.query_params, "type")
        if type_id is not None:
            qs = qs.filter(type_id=type_id)
        return qs
