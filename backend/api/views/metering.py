import os

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Prefetch
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from call_center.models import Invoice
from client.models import Client
from core.exceptions import ServiceError
from core.geo import UNSET
from metering import services as metering_services
from metering.constants import MeteringStatus
from metering.design.models import Design, DesignType
from metering.design.services import (
    add_design_type,
    mark_design_done,
    record_design_answer,
    set_design_due,
    set_designer,
)
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
    move_inventory_type,
    record_price_answer,
    rename_room,
    reorder_rooms,
    retire_object_type,
    save_calculation,
    save_version,
    set_image_furniture,
    set_price_due,
    set_pricer,
    split_inventory_type,
    version_offer_data,
)
from metering.services import (
    assign_metering_tasks,
    cancel_metering,
    create_metering,
    default_designer,
    default_manager,
    default_measurer,
    designers,
    finish_metering,
    managers,
    mark_metering_measured,
    measurers,
    metering_agenda,
    metering_files,
    metering_is_editable,
    metering_queryset_for,
    offer_agenda,
    offer_defaults,
    offer_queryset_for,
    presentations,
    pricers,
    reschedule_metering,
    save_metering_files,
    set_metering_location,
    set_metering_measurer,
    start_design,
    start_price,
)

from ..fields import MoneyField
from ..permissions import CatalogRead, IsStaffUser, ModelPermissions, PriceAccess, require_perm
from ..serializers.common import LocationSetSerializer, UserShortSerializer
from ..serializers.metering import (
    AssignTasksSerializer,
    CalculationInputSerializer,
    DesignDetailSerializer,
    DesignSerializer,
    DesignTypeSerializer,
    DontNeedSerializer,
    FinishSerializer,
    InventorySerializer,
    InventoryTypeSerializer,
    MeteringCreateSerializer,
    MeteringDetailSerializer,
    MeteringSerializer,
    MeteringShortSerializer,
    MeteringUpdateSerializer,
    ObjectTypeSerializer,
    OfferAnswerInputSerializer,
    OfferDueSerializer,
    OfferPersonSerializer,
    OtherDaySerializer,
    PriceDetailSerializer,
    PriceSerializer,
    RoomInputSerializer,
    RoomTypeSerializer,
    SetMeasurerSerializer,
    can_assign_tasks,
)
from ..serializers.offers import offer_brief
from ..utils import apply_period, csv_values, int_param, timeseries
from .files import _file_row


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
    if request.query_params.get("user") == "me":
        return qs.filter(user=request.user)
    user = int_param(request.query_params, "user")
    if user is not None:
        qs = qs.filter(user_id=user)
    return qs


def _presentation_row(row, ctx):
    """One «Mijozga ko'rsatish» row: serialized metering + design / price briefs."""
    from ..serializers.metering import _user

    m = row["metering"]
    design, price = row["design"], row["price"]
    design_brief = offer_brief(design, "design", ctx)
    if design_brief is not None:
        design_brief["types"] = DesignTypeSerializer(design.designtype_set.all(), many=True).data
    price_brief = offer_brief(price, "price", ctx)
    if price_brief is not None:
        price_brief["price"] = MoneyField().to_representation(price.price)
    return {
        "metering": MeteringShortSerializer(m, context=ctx).data,
        "design": design_brief,
        "price": price_brief,
        "manager": _user(m.manager),
        "waiting_for": row["waiting_for"],
        "is_overdue": row["is_overdue"],
    }


class MeteringViewSet(viewsets.ModelViewSet):
    permission_classes = [ModelPermissions]
    search_fields = ["client__fio", "client__phone", "address"]
    ordering_fields = ["date_time", "create_date"]
    ordering = ["-date_time"]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_permissions(self):
        # these check their own (offer) permissions: view_metering is not required
        if self.action in ("presentations", "assignees"):
            return [IsStaffUser()]
        return super().get_permissions()

    def get_serializer_class(self):
        if self.action == "retrieve":
            return MeteringDetailSerializer
        if self.action in ("update", "partial_update"):
            return MeteringUpdateSerializer
        return MeteringSerializer

    def base_queryset(self):
        qs = Metering.objects.select_related(
            "client",
            "design__user",
            "price__user",
            "order",
            "measurer",
            "manager",
            "created_by",
            "invoice__assigned_to",
        ).prefetch_related("offer_answers")
        return apply_period(qs, "create_date", self.request.query_params)

    def get_queryset(self):
        qs = metering_queryset_for(self.request.user, self.base_queryset())
        params = self.request.query_params
        statuses = csv_values(params.get("status"))
        if statuses:
            qs = qs.filter(status__in=statuses)
        return self._by_measurer(qs)

    def _by_measurer(self, qs):
        """?measurer=<id>|me"""
        value = self.request.query_params.get("measurer")
        if value == "me":
            return qs.filter(measurer=self.request.user)
        if value not in (None, ""):
            try:
                return qs.filter(measurer_id=int(value))
            except ValueError:
                return qs.none()
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
        if invoice is None and not request.user.is_superuser:
            # owner's rule: operators book a zamer from the lead (ariza); a zamer
            # without a lead is the admin's «Yangi o'lchov» on the O'lchovlar page
            raise ServiceError("O'lchov arizadan yaratiladi (Call-center)", "invoice")
        measurer_id = data.pop("measurer", None)
        measurer = get_object_or_404(get_user_model(), pk=measurer_id) if measurer_id else None
        with transaction.atomic():  # no orphan client if the metering is refused
            client = Client.objects.filter(phone=phone).first()
            if client is None:
                if not fio:
                    raise ServiceError("Yangi mijoz uchun F.I.Sh. kiriting")
                client = Client.objects.create(phone=phone, fio=fio)
            metering = create_metering(
                client=client, invoice=invoice, author=request.user, measurer=measurer, **data
            )
        return self._detail(metering, status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        metering = self.get_object()
        if not metering_is_editable(metering):
            raise PermissionDenied("Bajarilgan o'lchovni tahrirlab bo'lmaydi.")
        kwargs["partial"] = True
        super().update(request, *args, **kwargs)
        return self._detail(metering)

    @action(detail=True, methods=["post"])
    def location(self, request, pk=None):
        """Attach / clear the metering's map location: {location, address?}."""
        require_perm(request.user, "metering.change_metering")
        metering = self.get_object()
        body = LocationSetSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        d = body.validated_data
        set_metering_location(
            metering,
            point=d["point"],
            link=d["link"],
            address=d["address"] if "address" in d else UNSET,
            by=request.user,
        )
        response = self._detail(metering)
        response.data = {**response.data, "short": d["short"]}
        return response

    @action(
        detail=True, methods=["post"], url_path="dont-need", serializer_class=DontNeedSerializer
    )
    def dont_need(self, request, pk=None):
        """Cancel the zamer: {reason}. The lead goes back to its operator as a call task."""
        serializer = DontNeedSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        metering, returned = cancel_metering(
            self.get_object(), by=request.user, reason=serializer.validated_data["reason"]
        )
        response = self._detail(metering)
        response.data["lead_returned"] = returned
        return response

    @action(
        detail=True, methods=["post"], url_path="other-day", serializer_class=OtherDaySerializer
    )
    def other_day(self, request, pk=None):
        """Move the zamer to another time: {date_time} (required)."""
        serializer = OtherDaySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        metering = reschedule_metering(
            self.get_object(), by=request.user, date_time=serializer.validated_data["date_time"]
        )
        return self._detail(metering)

    @action(detail=True, methods=["post"], url_path="metering-done")
    def metering_done(self, request, pk=None):
        """«O'lchov oldim»: the measurer (or a zamer manager) took the measurements."""
        return self._detail(mark_metering_measured(self.get_object(), by=request.user))

    @action(detail=True, methods=["post"], serializer_class=FinishSerializer)
    def finish(self, request, pk=None):
        """«Bajarildi»: {note, next_step: design_price|price, designer?, pricer?, manager,
        design_due_at?, price_due_at?} - needs at least one uploaded file."""
        serializer = FinishSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        User = get_user_model()
        designer = get_object_or_404(User, pk=d["designer"]) if d.get("designer") else None
        pricer = get_object_or_404(User, pk=d["pricer"]) if d.get("pricer") else None
        manager = get_object_or_404(User, pk=d["manager"]) if d.get("manager") else None
        result = finish_metering(
            self.get_object(),
            by=request.user,
            note=d["note"],
            next_step=d["next_step"],
            designer=designer,
            pricer=pricer,
            manager=manager,
            design_due_at=d.get("design_due_at"),
            price_due_at=d.get("price_due_at"),
        )
        response = self._detail(result["metering"])
        response.data["assigned"] = result["assigned"]
        return response

    @action(detail=True, methods=["post"], serializer_class=SetMeasurerSerializer)
    def measurer(self, request, pk=None):
        """Hand the zamer to another measurer: {measurer}."""
        serializer = SetMeasurerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = get_object_or_404(get_user_model(), pk=serializer.validated_data["measurer"])
        return self._detail(
            set_metering_measurer(self.get_object(), measurer=user, by=request.user)
        )

    @action(
        detail=True,
        methods=["get", "post"],
        parser_classes=[MultiPartParser, FormParser],
    )
    def files(self, request, pk=None):
        """GET: files of the metering folder tree. POST multipart `file`: upload (one file
        per request from the SPA, so a big video shows real progress)."""
        metering = self.get_object()
        if request.method == "POST":
            uploads = request.FILES.getlist("file")
            if not uploads:
                raise ServiceError("Fayl tanlang", "files")
            created = save_metering_files(metering, uploads, by=request.user)
            return Response([_file_row(f) for f in created], status=status.HTTP_201_CREATED)
        rows = metering_files(metering).order_by("-uploaded_at")
        return Response([_file_row(f) for f in rows])

    @action(detail=True, methods=["post"])
    def estimate(self, request, pk=None):
        """The zamer's approximate price before «Bajarildi»: {id} — opened at /prices/{id}."""
        from metering.price.services import create_estimate

        price = create_estimate(metering=self.get_object(), by=request.user)
        return Response({"id": price.pk}, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"])
    def measurers(self, request):
        """Who can be picked as the measurer: {items: [UserShort], default: id|null}."""
        if not (
            request.user.has_perm("metering.add_metering")
            or request.user.has_perm("metering.change_metering")
            or request.user.has_perm("metering.manage_metering")
        ):
            raise PermissionDenied("Bu amal uchun huquq yetarli emas.")
        default = default_measurer()
        items = UserShortSerializer(measurers(), many=True).data
        body = {"items": items, "default": default.pk if default else None}
        if not items:
            body["hint"] = (
                "Zamerchi yo'q: xodimga «Metering» (user_metering) huquqini bering. "
                "Hozircha zamer zamerchisiz yaratiladi."
            )
        return Response(body)

    @action(detail=False, methods=["get"])
    def agenda(self, request):
        """The «Zamerlar» day agenda: counts + overdue / today / tomorrow / week / waiting."""
        qs = metering_queryset_for(request.user, self.base_queryset())
        qs = self._by_measurer(qs)
        search = (request.query_params.get("search") or "").strip()
        if search:
            from django.db.models import Q

            qs = qs.filter(
                Q(client__fio__icontains=search)
                | Q(client__phone__icontains=search)
                | Q(address__icontains=search)
            )
        data = metering_agenda(qs, now=metering_services._now())
        ctx = self.get_serializer_context()
        out = {"counts": data["counts"]}
        for key in ("overdue", "today", "tomorrow", "week", "waiting"):
            out[key] = MeteringSerializer(data[key], many=True, context=ctx).data
        return Response(out)

    @action(detail=True, methods=["post"], url_path="create-design")
    def create_design(self, request, pk=None):
        require_perm(request.user, "design.add_design")
        metering = self.get_object()
        start_design(metering, by=request.user)
        return self._detail(metering)

    @action(detail=False, methods=["get"])
    def assignees(self, request):
        """Who can be picked in "Назначить исполнителей" and «Bajarildi»: designers,
        pricers, managers (+ the preselected one), and the default deadlines."""
        user = request.user
        if not (
            can_assign_tasks(user)
            or user.has_perm("metering.manage_metering")
            or user.has_perm("metering.present_to_client")
        ):
            raise PermissionDenied("Bu amal uchun huquq yetarli emas.")
        manager_list = list(managers())
        default = default_manager()
        designer = default_designer()
        body = {
            "designers": UserShortSerializer(designers(), many=True).data,
            "pricers": UserShortSerializer(pricers(), many=True).data,
            "managers": UserShortSerializer(manager_list, many=True).data,
            "default_manager": default.pk if default else None,
            "default_designer": designer.pk if designer else None,
            "defaults": {
                k: (v.isoformat() if hasattr(v, "isoformat") else v)
                for k, v in offer_defaults(metering_services._now()).items()
            },
        }
        if not body["designers"]:
            body["designer_hint"] = (
                "Dizayner yo'q — Xodimlar → Lavozimlar: «Dizayner» lavozimiga xodim qo'shing"
            )
        if not body["pricers"]:
            body["pricer_hint"] = (
                "Menejer yo'q — narxni menejer hisoblaydi. Xodimlar → Lavozimlar: "
                "«Menejer» yoki «Bosh menejer» lavozimiga xodim qo'shing"
            )
        if not manager_list:
            body["hint"] = (
                "Menejer yo'q — Xodimlar → Lavozimlar: «Menejer» yoki «Bosh menejer» "
                "lavozimiga xodim qo'shing. Usiz zamerni yakunlab bo'lmaydi."
            )
        return Response(body)

    @action(detail=False, methods=["get"])
    def presentations(self, request):
        """«Mijozga ko'rsatish»: ?manager=me|<id>&search= -> {counts, review, working,
        order_ready}; row = {metering, design, price, manager, waiting_for, is_overdue}."""
        user = request.user
        if not (
            user.is_superuser
            or user.has_perm("metering.present_to_client")
            or user.has_perm("metering.manage_metering")
        ):
            raise PermissionDenied("Bu amal uchun huquq yetarli emas.")
        wanted = request.query_params.get("manager")
        if wanted == "me":
            wanted = user.pk
        else:
            wanted = int_param(request.query_params, "manager")
        data = presentations(
            user,
            now=metering_services._now(),
            manager=wanted,
            search=request.query_params.get("search") or "",
        )
        ctx = self.get_serializer_context()
        out = {
            key: [_presentation_row(r, ctx) for r in data[key]]
            for key in ("review", "working", "order_ready")
        }
        out["counts"] = data["counts"]
        return Response(out)

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
        result = assign_metering_tasks(metering, designer=designer, pricer=pricer, by=request.user)
        response = self._detail(metering)
        response.data["assigned"] = result
        return response

    @action(detail=True, methods=["post"], url_path="create-price")
    def create_price(self, request, pk=None):
        require_perm(request.user, "price.add_price")
        metering = self.get_object()
        start_price(metering, by=request.user)
        return self._detail(metering)

    @action(detail=False, methods=["get"])
    def stats(self, request):
        """Counts per status (the admin MeteringStatusBanner) + the line chart."""
        qs = self.filter_queryset(metering_queryset_for(request.user, self.base_queryset()))
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


def _offer_agenda_response(view, request, qs, kind):
    """GET agenda/: counts + overdue / today / work / review rows
    (?user=<id>|me, ?search=)."""
    from django.db.models import Q

    qs = offer_queryset_for(request.user, qs, kind=kind)
    who = request.query_params.get("user")
    if who == "me":
        qs = qs.filter(user=request.user)
    elif who not in (None, ""):  # (validated by _assignee_filter via the permission check)
        qs = qs.filter(user_id=int_param(request.query_params, "user") or 0)
    search = (request.query_params.get("search") or "").strip()
    if search:
        qs = qs.filter(
            Q(metering__client__fio__icontains=search)
            | Q(metering__client__phone__icontains=search)
            | Q(metering__address__icontains=search)
        )
    data = offer_agenda(qs, now=metering_services._now())
    ctx = view.get_serializer_context()
    out = {"counts": data["counts"]}
    for key in ("overdue", "today", "work", "review"):
        out[key] = view.get_serializer_class()(data[key], many=True, context=ctx).data
    return Response(out)


class DesignViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Designs are only created from a metering (MeteringViewSet.create_design)."""

    serializer_class = DesignSerializer
    permission_classes = [ModelPermissions]
    search_fields = ["metering__client__fio", "metering__client__phone"]
    ordering_fields = ["created_at", "due_at"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        return (
            DesignDetailSerializer
            if self.action != "list" and self.action != "agenda"
            else DesignSerializer
        )

    def get_queryset(self):
        qs = Design.objects.select_related(
            "metering__client",
            "metering__order",
            "metering__manager",
            "metering__measurer",
            "user",
        ).prefetch_related("designtype_set", "metering__offer_answers")
        params = self.request.query_params
        qs = _assignee_filter(qs, self.request)
        for field in ("done", "confirm"):
            value = _bool_param(params.get(field))
            if value is not None:
                qs = qs.filter(**{field: value})
        stages = csv_values(params.get("stage"))
        if stages:
            qs = qs.filter(stage__in=stages)
        return apply_period(qs, "created_at", params)

    def _detail(self, design):
        design = self.get_queryset().get(pk=design.pk)
        return Response(DesignDetailSerializer(design, context=self.get_serializer_context()).data)

    @action(detail=False, methods=["get"])
    def agenda(self, request):
        return _offer_agenda_response(
            self,
            request,
            Design.objects.select_related(
                "metering__client",
                "metering__order",
                "metering__manager",
                "metering__measurer",
                "user",
            ).prefetch_related("designtype_set", "metering__offer_answers"),
            "design",
        )

    @action(detail=True, methods=["post"])
    def done(self, request, pk=None):
        require_perm(request.user, "design.change_design")
        return self._detail(mark_design_done(self.get_object(), by=request.user))

    @action(detail=True, methods=["post"], serializer_class=OfferDueSerializer)
    def due(self, request, pk=None):
        """Move the deadline: {due_at}."""
        body = OfferDueSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        set_design_due(self.get_object(), by=request.user, due_at=body.validated_data["due_at"])
        return self._detail(self.get_object())

    @action(detail=True, methods=["post"], serializer_class=OfferPersonSerializer)
    def designer(self, request, pk=None):
        """Hand the design to another designer: {user}."""
        body = OfferPersonSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        user = get_object_or_404(get_user_model(), pk=body.validated_data["user"])
        set_designer(self.get_object(), by=request.user, user=user)
        return self._detail(self.get_object())

    @action(detail=True, methods=["post"], serializer_class=OfferAnswerInputSerializer)
    def answer(self, request, pk=None):
        """The client's answer, recorded by the manager: {answer: approved|changes|declined,
        comment?, due_at?}."""
        body = OfferAnswerInputSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        d = body.validated_data
        result = record_design_answer(
            self.get_object(),
            by=request.user,
            answer=d["answer"],
            comment=d["comment"],
            due_at=d["due_at"],
        )
        response = self._detail(result["task"])
        response.data["closed_tasks"] = result["closed_tasks"]
        return response

    @action(detail=True, methods=["post"], serializer_class=DesignTypeSerializer)
    def types(self, request, pk=None):
        """Add one more design variant (the admin's DesignType inline)."""
        require_perm(request.user, "design.add_designtype")
        design = self.get_object()
        serializer = DesignTypeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        add_design_type(design, serializer.validated_data["name"])
        return self._detail(design)


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


class AssignPricesSerializer(serializers.Serializer):
    user = serializers.IntegerField()
    due_at = serializers.DateTimeField()
    count = serializers.IntegerField(required=False, allow_null=True, min_value=1)


class PriceViewSet(viewsets.ModelViewSet):
    # the price rights, or a lead's approximate price for whoever works the lead
    permission_classes = [PriceAccess]
    search_fields = ["metering__client__fio", "metering__client__phone", "desc"]
    ordering_fields = ["created_at"]
    ordering = ["-created_at"]
    # DELETE is only for the nested calculations / rooms / images, never the price itself
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def destroy(self, request, *args, **kwargs):
        """Only a lead's approximate price, until the zamer is finished."""
        from metering.price.services import delete_estimate, is_estimate

        price = self.get_object()
        if not is_estimate(price):
            raise MethodNotAllowed("DELETE")
        delete_estimate(price, by=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _need(self, request, *perms):
        """The price rights — or this price is a lead's approximate price (PriceAccess
        already let only its workers reach it)."""
        from metering.price.services import can_open_estimate

        if request.user.has_perms(perms):
            return
        if not can_open_estimate(request.user, self.get_object()):
            raise PermissionDenied("Bu amal uchun huquq yetarli emas.")

    def get_serializer_class(self):
        if self.action in ("retrieve", "create", "partial_update", "update"):
            return PriceDetailSerializer
        return PriceSerializer

    def get_queryset(self):
        qs = self._base()
        params = self.request.query_params
        qs = _assignee_filter(qs, self.request)
        done = _bool_param(params.get("done"))
        if done is not None:
            qs = qs.filter(done=done)
        stages = csv_values(params.get("stage"))
        if stages:
            qs = qs.filter(stage__in=stages)
        has_metering = _bool_param(params.get("has_metering"))
        if has_metering is not None:
            qs = qs.filter(metering__isnull=not has_metering)
        return apply_period(qs, "created_at", params)

    @staticmethod
    def _base():
        return Price.objects.select_related(
            "metering__client",
            "metering__order",
            "metering__manager",
            "metering__measurer",
            "user",
        ).prefetch_related("metering__offer_answers")

    def _detail(self, price):
        price = self.get_queryset().get(pk=price.pk)
        return Response(PriceDetailSerializer(price, context=self.get_serializer_context()).data)

    @action(detail=False, methods=["get"])
    def agenda(self, request):
        return _offer_agenda_response(self, request, self._base(), "price")

    @action(detail=False, methods=["get"], url_path="unassigned")
    def unassigned(self, request):
        """Admin: the prices nobody calculates, to review before deleting the old ones."""
        from metering.price.services import unassigned_prices

        if not request.user.is_superuser:
            raise PermissionDenied("Faqat administrator uchun")
        rows = unassigned_prices().select_related("metering__client", "metering__order")
        out = []
        for p in rows:
            m = p.metering
            out.append(
                {
                    "id": p.pk,
                    "client": m.client.fio if m else (p.desc or f"#{p.pk}"),
                    "phone": str(m.client.phone) if m else "",
                    "created_at": p.created_at,
                    "has_order": bool(m and getattr(m, "order", None)),
                }
            )
        return Response(out)

    @action(detail=False, methods=["post"], url_path="unassigned/delete")
    def delete_unassigned(self, request):
        """Admin: {ids: [...]} — delete those old prices (one that became an order stays)."""
        from metering.price.services import delete_unassigned_prices

        ids = request.data.get("ids")
        if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
            raise ValidationError({"ids": "Narxlar ro'yxati kerak"})
        return Response(delete_unassigned_prices(by=request.user, ids=ids))

    @action(detail=False, methods=["get", "post"], url_path="assign")
    def assign_unassigned(self, request):
        """Prices in work nobody calculates. GET {unassigned}; POST {user, due_at, count?}
        gives the oldest `count` (all) to that manager with the deadline (admin / bosh
        menejer; the manager gets them in the bot)."""
        from metering.price.services import assign_prices, unassigned_prices

        if request.method == "GET":
            return Response({"unassigned": unassigned_prices().count()})
        body = AssignPricesSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        d = body.validated_data
        user = get_object_or_404(get_user_model(), pk=d["user"])
        return Response(
            assign_prices(by=request.user, user=user, due_at=d["due_at"], count=d.get("count"))
        )

    @action(detail=True, methods=["post"])
    def done(self, request, pk=None):
        require_perm(request.user, "price.change_price")
        return self._detail(mark_price_done(self.get_object(), by=request.user))

    @action(detail=True, methods=["post"], serializer_class=OfferDueSerializer)
    def due(self, request, pk=None):
        """Move the deadline: {due_at}."""
        body = OfferDueSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        set_price_due(self.get_object(), by=request.user, due_at=body.validated_data["due_at"])
        return self._detail(self.get_object())

    @action(detail=True, methods=["post"], serializer_class=OfferPersonSerializer)
    def pricer(self, request, pk=None):
        """Hand the calculation to another person: {user}."""
        body = OfferPersonSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        user = get_object_or_404(get_user_model(), pk=body.validated_data["user"])
        set_pricer(self.get_object(), by=request.user, user=user)
        return self._detail(self.get_object())

    @action(detail=True, methods=["post"], serializer_class=OfferAnswerInputSerializer)
    def answer(self, request, pk=None):
        """The client's answer, recorded by the manager: {answer: approved|recalc|declined,
        comment?, due_at?}."""
        body = OfferAnswerInputSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        d = body.validated_data
        result = record_price_answer(
            self.get_object(),
            by=request.user,
            answer=d["answer"],
            comment=d["comment"],
            due_at=d["due_at"],
        )
        response = self._detail(result["task"])
        response.data["closed_tasks"] = result["closed_tasks"]
        return response

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
        self._need(request, "price.change_price")
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
        self._need(request, "price.change_price", "price.add_calculate", "price.change_calculate")
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
            self._need(request, "price.delete_calculate")
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
        self._need(request, "price.change_price", "price.add_calculate")
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
        self._need(request, "price.change_price")
        price = self.get_object()
        calc = get_object_or_404(Calculate, pk=calc_id, price=price)
        self._need(
            request,
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
    """Archived objects are listed too (old calculations show their name); the UI
    hides them from the catalog and from new furniture."""

    queryset = ObjectType.objects.order_by("pk")
    serializer_class = ObjectTypeSerializer
    permission_classes = [CatalogRead]
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def destroy(self, request, *args, **kwargs):
        result = retire_object_type(self.get_object())
        if result == "archived":
            return Response({"result": result, "detail": "Eski hisob-kitoblarda bor — arxivlandi"})
        return Response(status=status.HTTP_204_NO_CONTENT)


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
        from metering.price.services import can_estimate

        if not can_estimate(request.user):  # else the price staff: price.view_price
            require_perm(request.user, "price.view_price")
        return super().list(request, *args, **kwargs)

    def perform_destroy(self, instance):
        if instance.rooms.exists():
            raise ServiceError("Bu xona turi hisob-kitoblarda ishlatilgan — o'chirib bo'lmaydi")
        instance.delete()


class InventoryTypeViewSet(viewsets.ModelViewSet):
    serializer_class = InventoryTypeSerializer
    permission_classes = [CatalogRead]
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

    @action(detail=True, methods=["post"])
    def move(self, request, pk=None):
        """Move the card with its products to another object: {obj}."""
        require_perm(request.user, "price.change_inventorytype")
        inv_type = self.get_object()
        obj = get_object_or_404(ObjectType, pk=int_param(request.data, "obj") or 0)
        move_inventory_type(inv_type, obj)
        return Response(self.get_serializer(inv_type).data)

    @action(detail=True, methods=["post"])
    def split(self, request, pk=None):
        """Make the card its own object (its products move along)."""
        require_perm(request.user, "price.change_inventorytype")
        require_perm(request.user, "price.add_objecttype")
        obj = split_inventory_type(self.get_object())
        return Response(ObjectTypeSerializer(obj).data)


class InventoryViewSet(viewsets.ModelViewSet):
    serializer_class = InventorySerializer
    permission_classes = [CatalogRead]
    pagination_class = None
    search_fields = ["name"]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = Inventory.objects.select_related("type").order_by("name")
        type_id = int_param(self.request.query_params, "type")
        if type_id is not None:
            qs = qs.filter(type_id=type_id)
        return qs
