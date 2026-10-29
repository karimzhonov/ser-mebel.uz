import os

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Prefetch
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, PermissionDenied
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from call_center.models import Invoice
from client.models import Client
from core.exceptions import ServiceError
from metering.constants import MeteringStatus
from metering.design.models import Design, DesignType
from metering.design.services import add_design_type, mark_design_done
from metering.models import Metering
from metering.price.models import (
    Calculate,
    Inventory,
    InventoryType,
    ObjectType,
    Price,
    PriceVersion,
    Room,
    RoomImage,
    RoomType,
)
from metering.price.services import (
    add_accessory_image,
    add_room,
    add_room_images,
    delete_calculation,
    delete_room,
    delete_room_image,
    mark_price_done,
    rename_room,
    reorder_rooms,
    save_calculation,
    save_version,
    set_image_furniture,
    version_offer_data,
)
from metering.services import (
    assign_metering_tasks,
    create_metering,
    designers,
    mark_metering_done,
    mark_metering_dont_need,
    mark_metering_other_day,
    metering_is_editable,
    pricers,
    start_design,
    start_price,
)
from oauth.constants import METERING_PERMISSION

from ..permissions import IsStaffUser, ModelPermissions, require_perm
from ..serializers.common import UserShortSerializer
from ..serializers.metering import (
    AssignTasksSerializer,
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
    RoomInputSerializer,
    RoomTypeSerializer,
    can_assign_tasks,
)
from ..utils import apply_period, csv_values, int_param, timeseries


def _bool_param(value):
    if value in ("true", "True", "1"):
        return True
    if value in ("false", "False", "0"):
        return False
    return None


def _assignee_filter(qs, request):
    """?mine=1 — tasks assigned to me; ?user=<id> — tasks of one executor."""
    if _bool_param(request.query_params.get("mine")):
        qs = qs.filter(user=request.user)
    user = int_param(request.query_params, "user")
    if user is not None:
        qs = qs.filter(user_id=user)
    return qs


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
        qs = Metering.objects.select_related("client", "design__user", "price__user", "order")
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
                    raise ServiceError("Yangi mijoz uchun F.I.Sh. kiriting")
                client = Client.objects.create(phone=phone, fio=fio)
            metering = create_metering(client=client, invoice=invoice, **data)
        return self._detail(metering, status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        metering = self.get_object()
        if not metering_is_editable(metering):
            raise PermissionDenied("Bajarilgan o'lchovni tahrirlab bo'lmaydi.")
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

    @action(detail=False, methods=["get"])
    def assignees(self, request):
        """Who can be picked in "Назначить исполнителей"."""
        if not can_assign_tasks(request.user):
            raise PermissionDenied("Bu amal uchun huquq yetarli emas.")
        return Response(
            {
                "designers": UserShortSerializer(designers(), many=True).data,
                "pricers": UserShortSerializer(pricers(), many=True).data,
            }
        )

    @action(detail=True, methods=["post"], serializer_class=AssignTasksSerializer)
    def assign(self, request, pk=None):
        """Give the design and/or price task to one person each; they get it in Telegram."""
        if not can_assign_tasks(request.user):
            raise PermissionDenied("Bu amal uchun huquq yetarli emas.")
        metering = self.get_object()
        serializer = AssignTasksSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = serializer.validated_data
        User = get_user_model()
        designer = get_object_or_404(User, pk=ids["designer"]) if ids.get("designer") else None
        pricer = get_object_or_404(User, pk=ids["pricer"]) if ids.get("pricer") else None
        result = assign_metering_tasks(metering, designer=designer, pricer=pricer)
        response = self._detail(metering)
        response.data["assigned"] = result
        return response

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
        qs = Design.objects.select_related(
            "metering__client", "metering__order", "user"
        ).prefetch_related("designtype_set")
        params = self.request.query_params
        qs = _assignee_filter(qs, self.request)
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
            raise ServiceError("Bu variant buyurtmada ishlatilgan — o'chirib bo'lmaydi")
        instance.delete()


class PriceViewSet(viewsets.ModelViewSet):
    permission_classes = [ModelPermissions]
    search_fields = ["metering__client__fio", "metering__client__phone", "desc"]
    ordering_fields = ["created_at"]
    ordering = ["-created_at"]
    # DELETE is only for the nested calculations / rooms / images, never the price itself
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def destroy(self, request, *args, **kwargs):
        raise MethodNotAllowed("DELETE")

    def get_serializer_class(self):
        if self.action in ("retrieve", "create", "partial_update", "update"):
            return PriceDetailSerializer
        return PriceSerializer

    def get_queryset(self):
        qs = Price.objects.select_related("metering__client", "metering__order", "user")
        params = self.request.query_params
        qs = _assignee_filter(qs, self.request)
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
        from metering.price.excel import build_offer_xlsx

        price = self.get_object()
        resp = HttpResponse(
            build_offer_xlsx(price),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        resp["Content-Disposition"] = f'attachment; filename="hisob-{price.pk}.xlsx"'
        return resp

    @action(detail=True, methods=["get"])
    def pdf(self, request, pk=None):
        """The commercial offer («Тижорат таклифи») for the client."""
        from metering.price.offer_pdf import build_offer_pdf

        price = self.get_object()
        resp = HttpResponse(build_offer_pdf(price), content_type="application/pdf")
        resp["Content-Disposition"] = f'inline; filename="taklif-{price.pk}.pdf"'
        return resp

    # --- versions: the offer as given to the client ----------------------------------

    @action(detail=True, methods=["post"], url_path="versions")
    def add_version(self, request, pk=None):
        require_perm(request.user, "price.change_price")
        price = self.get_object()
        save_version(request.user, price, (request.data.get("label") or "").strip())
        return self._detail(price)

    @action(detail=True, methods=["get"], url_path=r"versions/(?P<version_id>\d+)/pdf")
    def version_pdf(self, request, pk=None, version_id=None):
        from metering.price.offer_pdf import build_offer_pdf

        price = self.get_object()
        v = get_object_or_404(PriceVersion, pk=version_id, price=price)
        resp = HttpResponse(
            build_offer_pdf(data=version_offer_data(v)), content_type="application/pdf"
        )
        resp["Content-Disposition"] = f'inline; filename="taklif-{price.pk}-v{v.number}.pdf"'
        return resp

    @action(
        detail=True,
        methods=["post"],
        url_path="accessory-images",
        parser_classes=[MultiPartParser, FormParser],
    )
    def accessory_image(self, request, pk=None):
        """One picture for an accessory row; the editor sends its id back on save."""
        from .files import _thumbnail

        price = self._editable_price(request)
        up = request.FILES.get("file")
        if up is None:
            raise ServiceError("Rasm tanlanmagan")
        self._check_image(up)
        img = add_accessory_image(request.user, price, up)
        return Response(
            {"image": img.pk, "thumbnail": _thumbnail(img), "name": img.original_filename}
        )

    @staticmethod
    def _check_image(up):
        from .files import IMAGE_EXTENSIONS, _normalize_upload_name

        name = _normalize_upload_name(up, lambda: "")
        if not name or os.path.splitext(name)[1].lower() not in IMAGE_EXTENSIONS:
            raise ServiceError(f"«{up.name}» rasm emas (JPG, PNG, WEBP …)")
        up.name = name

    # --- rooms ---------------------------------------------------------------------

    def _editable_price(self, request):
        require_perm(
            request.user, "price.change_price", "price.add_calculate", "price.change_calculate"
        )
        return self.get_object()

    def _room_of(self, price, room_id):
        if room_id in (None, ""):
            return None
        return get_object_or_404(Room.objects.select_related("room_type"), pk=room_id, price=price)

    @action(detail=True, methods=["post"], url_path="rooms", serializer_class=RoomInputSerializer)
    def add_room(self, request, pk=None):
        price = self._editable_price(request)
        s = RoomInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        add_room(price, s.validated_data["room_type"], s.validated_data.get("name", ""))
        return self._detail(price)

    @action(detail=True, methods=["post"], url_path="rooms/reorder")
    def reorder_rooms(self, request, pk=None):
        price = self._editable_price(request)
        ids = request.data.get("ids")
        if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
            raise ServiceError("ids: xona id'lari ro'yxati kerak")
        reorder_rooms(price, ids)
        return self._detail(price)

    @action(detail=True, methods=["patch", "delete"], url_path=r"rooms/(?P<room_id>\d+)")
    def room(self, request, pk=None, room_id=None):
        price = self._editable_price(request)
        room = self._room_of(price, room_id)
        if request.method == "DELETE":
            require_perm(request.user, "price.delete_calculate")
            delete_room(room)
        else:
            rename_room(room, request.data.get("name", ""))
        return self._detail(price)

    @action(
        detail=True,
        methods=["post"],
        url_path=r"rooms/(?P<room_id>\d+)/images",
        parser_classes=[MultiPartParser, FormParser],
    )
    def room_images(self, request, pk=None, room_id=None):
        price = self._editable_price(request)
        room = self._room_of(price, room_id)
        uploads = request.FILES.getlist("file")
        if not uploads:
            raise ServiceError("Rasm tanlanmagan")
        for up in uploads:
            self._check_image(up)
        calc = None
        if request.data.get("calculate"):
            calc = get_object_or_404(Calculate, pk=request.data["calculate"], room=room)
        add_room_images(request.user, room, uploads, calc)
        return self._detail(price)

    @action(
        detail=True,
        methods=["patch", "delete"],
        url_path=r"rooms/(?P<room_id>\d+)/images/(?P<image_id>\d+)",
    )
    def room_image(self, request, pk=None, room_id=None, image_id=None):
        """PATCH {"calculate": id | null}: which furniture the picture shows."""
        price = self._editable_price(request)
        room = self._room_of(price, room_id)
        image = get_object_or_404(RoomImage, pk=image_id, room=room)
        if request.method == "DELETE":
            delete_room_image(image)
        else:
            calc_id = request.data.get("calculate")
            calc = get_object_or_404(Calculate, pk=calc_id, room=room) if calc_id else None
            set_image_furniture(image, calc)
        return self._detail(price)

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
            room=self._room_of(price, data.get("room")),
            note=data.get("note", ""),
            color=data.get("color", ""),
            manual_amount=data.get("manual_amount"),
            accessories=data.get("accessories", []),
            unit=data.get("unit", ""),
            height=data.get("height"),
            width=data.get("width"),
            depth=data.get("depth"),
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
            room=self._room_of(price, data.get("room")),
            note=data.get("note", ""),
            color=data.get("color", ""),
            manual_amount=data.get("manual_amount"),
            accessories=data.get("accessories", []),
            unit=data.get("unit", ""),
            height=data.get("height"),
            width=data.get("width"),
            depth=data.get("depth"),
        )
        return self._detail(price)


class ObjectTypeViewSet(viewsets.ModelViewSet):
    queryset = ObjectType.objects.order_by("pk")
    serializer_class = ObjectTypeSerializer
    permission_classes = [ModelPermissions]
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]


class RoomTypeViewSet(viewsets.ModelViewSet):
    """Xona turlari. Everyone who calculates prices reads them; managing them needs
    the price.*_roomtype permissions (superusers)."""

    queryset = RoomType.objects.prefetch_related("object_types").order_by("ordering", "name")
    serializer_class = RoomTypeSerializer
    permission_classes = [ModelPermissions]
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [IsStaffUser()]
        return super().get_permissions()

    def list(self, request, *args, **kwargs):
        require_perm(request.user, "price.view_price")
        return super().list(request, *args, **kwargs)

    def perform_destroy(self, instance):
        if instance.rooms.exists():
            raise ServiceError("Bu xona turi hisob-kitoblarda ishlatilgan — o'chirib bo'lmaydi")
        instance.delete()


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
