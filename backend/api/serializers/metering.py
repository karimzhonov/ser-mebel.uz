from phonenumber_field.serializerfields import PhoneNumberField
from rest_framework import serializers

from metering import services as metering_services
from metering.constants import MeteringStatus
from metering.design.models import Design, DesignType
from metering.models import Metering
from metering.price.models import (
    Calculate,
    Inventory,
    InventoryInCalculate,
    InventoryType,
    ObjectType,
    Price,
    Room,
    RoomType,
)
from metering.services import (
    ASSIGNABLE_STATUSES,
    CANCELLABLE_STATUSES,
    OPEN_STATUSES,
    can_reschedule_or_cancel,
    can_work_metering,
    is_overdue,
    metering_files,
    metering_is_editable,
    metering_operator,
)
from oauth.constants import METERING_PERMISSION

from .. import i18n as uz
from ..fields import MoneyField
from .common import (
    ClientShortSerializer,
    LocationFieldsMixin,
    LocationInputMixin,
    OrderSummarySerializer,
    UserShortSerializer,
    order_of,
)
from .offers import OfferAnswerSerializer, OfferFieldsMixin, offer_brief


def _user(user):
    return UserShortSerializer(user).data if user is not None else None


def can_assign_tasks(user) -> bool:
    """The metering staff (who press "Замер выполнен") or whoever may edit meterings."""
    return (
        user.has_perm(f"oauth.{METERING_PERMISSION}")
        or user.has_perm("metering.change_metering")
        or user.has_perm("metering.manage_metering")
    )


def _brief_extra(brief):
    """The stage-2 part of a design / price brief (id and user are already there)."""
    return {k: v for k, v in brief.items() if k not in ("id", "user")}


def _order_summary(metering, context):
    order = order_of(metering)
    return OrderSummarySerializer(order, context=context).data if order else None


class MeteringShortSerializer(LocationFieldsMixin, serializers.ModelSerializer):
    client = ClientShortSerializer(read_only=True)

    class Meta:
        model = Metering
        fields = [
            "id",
            "client",
            "address",
            "address_link",
            "lat",
            "lon",
            "map_url",
            "date_time",
            "status",
            "folder",
        ]


class MeteringSerializer(LocationFieldsMixin, serializers.ModelSerializer):
    client = ClientShortSerializer(read_only=True)
    status_label = serializers.SerializerMethodField()
    design = serializers.SerializerMethodField()
    price = serializers.SerializerMethodField()
    order = serializers.SerializerMethodField()
    is_editable = serializers.SerializerMethodField()
    measurer = serializers.SerializerMethodField()
    manager = serializers.SerializerMethodField()
    operator = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()

    class Meta:
        model = Metering
        fields = [
            "id",
            "client",
            "status",
            "status_label",
            "date_time",
            "measurer",
            "manager",
            "client_result",
            "operator",
            "measured_at",
            "done_at",
            "result_note",
            "next_step",
            "cancel_reason",
            "is_overdue",
            "rev",
            "address",
            "address_link",
            "lat",
            "lon",
            "map_url",
            "desc",
            "create_date",
            "invoice",
            "folder",
            "design",
            "price",
            "order",
            "is_editable",
        ]
        read_only_fields = fields

    def get_status_label(self, obj):
        return uz.metering_status(obj.status)

    def get_design(self, obj):
        design = getattr(obj, "design", None)
        if design is None:
            return None
        return {
            "id": design.pk,
            "done": design.done,
            "confirm": design.confirm,
            "user": _user(design.user),
            **_brief_extra(offer_brief(design, "design", self.context)),
        }

    def get_price(self, obj):
        price = getattr(obj, "price", None)
        if price is None:
            return None
        return {
            "id": price.pk,
            "done": price.done,
            "user": _user(price.user),
            **_brief_extra(offer_brief(price, "price", self.context)),
        }

    def get_order(self, obj):
        return _order_summary(obj, self.context)

    def get_is_editable(self, obj):
        return metering_is_editable(obj)

    def get_measurer(self, obj):
        return _user(obj.measurer)

    def get_manager(self, obj):
        return _user(obj.manager)

    def get_operator(self, obj):
        return _user(metering_operator(obj))

    def get_is_overdue(self, obj):
        # one clock reading and one constance lookup per serialization run: the root
        # context is shared by every child of a ListSerializer
        ctx = self.context
        if "_met_now" not in ctx:
            ctx["_met_now"] = metering_services._now()
            ctx["_met_late_after"] = metering_services._late_after()
        return is_overdue(obj, ctx["_met_now"], ctx["_met_late_after"])


class MeteringDetailSerializer(MeteringSerializer):
    actions = serializers.SerializerMethodField()
    file_count = serializers.SerializerMethodField()

    class Meta(MeteringSerializer.Meta):
        fields = MeteringSerializer.Meta.fields + ["file_count", "actions"]
        read_only_fields = fields

    def get_file_count(self, obj):
        return metering_files(obj).count()

    def get_actions(self, obj):
        """Which buttons this user gets."""
        user = self.context["request"].user
        status = obj.status
        S = MeteringStatus
        can_change = user.has_perm("metering.change_metering")
        manager = user.is_superuser or user.has_perm("metering.manage_metering")
        work = can_work_metering(user, obj)
        measured = work and status in OPEN_STATUSES
        return {
            "edit": can_change and metering_is_editable(obj),
            "measured": measured,
            "metering_done": measured,  # old name of "measured" (kept for old clients)
            "reschedule": can_reschedule_or_cancel(user, obj) and status in OPEN_STATUSES,
            "cancel": can_reschedule_or_cancel(user, obj) and status in CANCELLABLE_STATUSES,
            "finish": work and status == S.metering_done,
            "upload": can_reschedule_or_cancel(user, obj)
            and status not in (S.dont_need, S.sold_out),
            "set_measurer": (manager or can_change) and status in [*OPEN_STATUSES, S.metering_done],
            "create_design": user.has_perm("design.add_design") and not hasattr(obj, "design"),
            "create_price": user.has_perm("price.add_price") and not hasattr(obj, "price"),
            # "Назначить исполнителей": after the metering, while a task is still open.
            "assign": can_assign_tasks(user)
            and status in ASSIGNABLE_STATUSES
            and not (
                getattr(getattr(obj, "design", None), "done", False)
                and getattr(getattr(obj, "price", None), "done", False)
            ),
        }


class MeteringCreateSerializer(LocationInputMixin, serializers.Serializer):
    client_phone = PhoneNumberField(region="UZ")
    client_fio = serializers.CharField(max_length=255, required=False, allow_blank=True)
    date_time = serializers.DateTimeField()
    address = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    address_link = serializers.URLField(
        max_length=1000, required=False, allow_blank=True, allow_null=True
    )
    desc = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    invoice = serializers.IntegerField(required=False, allow_null=True)
    measurer = serializers.IntegerField(required=False, allow_null=True)


class MeteringUpdateSerializer(serializers.ModelSerializer):
    """Only the description is editable: the time moves through «reschedule» (it is
    versioned and told to the measurer)."""

    class Meta:
        model = Metering
        fields = ["desc"]


class OtherDaySerializer(serializers.Serializer):
    date_time = serializers.DateTimeField()


class DontNeedSerializer(serializers.Serializer):
    reason = serializers.CharField(trim_whitespace=True)


class FinishSerializer(serializers.Serializer):
    note = serializers.CharField(allow_blank=True, required=False, default="")
    next_step = serializers.CharField(allow_blank=True, required=False, default="")
    designer = serializers.IntegerField(required=False, allow_null=True)
    pricer = serializers.IntegerField(required=False, allow_null=True)
    manager = serializers.IntegerField(required=False, allow_null=True)
    design_due_at = serializers.DateTimeField(required=False, allow_null=True)
    price_due_at = serializers.DateTimeField(required=False, allow_null=True)


class SetMeasurerSerializer(serializers.Serializer):
    measurer = serializers.IntegerField()


# --- Design ---------------------------------------------------------------------


class DesignTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = DesignType
        fields = ["id", "name", "folder", "created_at"]
        read_only_fields = ["folder", "created_at"]


def _offer_actions(user, obj, kind):
    """The stage-2 buttons of a Design / Price for this user (service predicates)."""
    from metering.design.services import can_work_design
    from metering.price.services import can_work_price

    can_work = can_work_design if kind == "design" else can_work_price
    manage = user.has_perm("metering.manage_metering")
    m = obj.metering
    return {
        "done": user.has_perm(f"{kind}.change_{kind}")
        and can_work(user, obj)
        and obj.stage == "work",
        "due": (can_work(user, obj) or manage) and obj.stage == "work",
        "reassign": (user.is_superuser or manage) and obj.stage == "work",
        "answer": m is not None
        and metering_services.can_present(user, m)
        and obj.stage == "review",
    }


class DesignSerializer(OfferFieldsMixin, serializers.ModelSerializer):
    kind = "design"
    metering = MeteringShortSerializer(read_only=True)
    user_detail = UserShortSerializer(source="user", read_only=True)
    order = serializers.SerializerMethodField()
    types = DesignTypeSerializer(source="designtype_set", many=True, read_only=True)
    actions = serializers.SerializerMethodField()

    class Meta:
        model = Design
        fields = [
            "id",
            "metering",
            "created_at",
            "done",
            "confirm",
            "user_detail",
            "types",
            "order",
            "actions",
            *OfferFieldsMixin.OFFER_FIELDS,
        ]
        read_only_fields = fields

    def get_order(self, obj):
        return _order_summary(obj.metering, self.context)

    def get_actions(self, obj):
        user = self.context["request"].user
        return {
            **_offer_actions(user, obj, "design"),
            "add_type": user.has_perm("design.add_designtype"),
            # can_create_order(), minus its query: metering__order is select_related.
            "create_order": user.has_perm("order.add_order")
            and obj.stage == "approved"
            and obj.metering.client_result not in ("design_declined", "price_declined")
            and order_of(obj.metering) is None,
        }


class DesignDetailSerializer(DesignSerializer):
    answers = serializers.SerializerMethodField()
    file_count = serializers.SerializerMethodField()

    class Meta(DesignSerializer.Meta):
        fields = DesignSerializer.Meta.fields + ["answers", "file_count"]
        read_only_fields = fields

    def get_answers(self, obj):
        rows = [a for a in obj.metering.offer_answers.all() if a.kind == "design"]
        return OfferAnswerSerializer(rows, many=True).data

    def get_file_count(self, obj):
        from metering.design.services import design_file_count

        return design_file_count(obj)


class OfferDueSerializer(serializers.Serializer):
    due_at = serializers.DateTimeField()


class OfferPersonSerializer(serializers.Serializer):
    user = serializers.IntegerField()


class OfferAnswerInputSerializer(serializers.Serializer):
    answer = serializers.CharField()
    comment = serializers.CharField(required=False, allow_blank=True, default="")
    due_at = serializers.DateTimeField(required=False, allow_null=True, default=None)


# --- Price ----------------------------------------------------------------------


class ObjectTypeSerializer(serializers.ModelSerializer):
    count_label = serializers.SerializerMethodField()

    def get_count_label(self, obj):
        return uz.COUNT_NAME.get(obj.count_name, obj.get_count_name_display())

    class Meta:
        model = ObjectType
        fields = ["id", "name", "count_name", "count_label", "show_area", "archived"]


class InventorySerializer(serializers.ModelSerializer):
    price = MoneyField(allow_null=True, required=False)

    class Meta:
        model = Inventory
        fields = ["id", "name", "type", "price"]


class InventoryTypeSerializer(serializers.ModelSerializer):
    type_label = serializers.SerializerMethodField()

    def get_type_label(self, obj):
        return uz.INVENTORY_KIND.get(obj.type, obj.get_type_display())

    inventories = InventorySerializer(source="inventory_set", many=True, read_only=True)

    def validate_obj(self, obj):
        if obj is not None and obj.archived:
            raise serializers.ValidationError(f"«{obj.name}» arxivda")
        return obj

    class Meta:
        model = InventoryType
        fields = ["id", "name", "obj", "type", "type_label", "ordering", "inventories"]


class CalculationItemSerializer(serializers.ModelSerializer):
    inventory_type = serializers.IntegerField(source="inventory.type_id", read_only=True)
    inventory_type_name = serializers.CharField(source="inventory.type.name", read_only=True)
    inventory_name = serializers.CharField(source="inventory.name", read_only=True)
    price = MoneyField(read_only=True)

    class Meta:
        model = InventoryInCalculate
        fields = [
            "id",
            "inventory_type",
            "inventory_type_name",
            "inventory",
            "inventory_name",
            "count",
            "price",
        ]


class CalculationSerializer(serializers.ModelSerializer):
    amount = MoneyField(read_only=True)
    items = CalculationItemSerializer(source="inventoryincalculate_set", many=True, read_only=True)
    accessories = serializers.SerializerMethodField()

    class Meta:
        model = Calculate
        fields = [
            "id",
            "name",
            "count",
            "obj",
            "room",
            "note",
            "color",
            "unit",
            "height",
            "width",
            "depth",
            "auto_amount",
            "manual_amount",
            "amount",
            "items",
            "accessories",
        ]

    def get_accessories(self, obj):
        from ..views.files import _thumbnail

        return [
            {
                "id": a.id,
                "inventory": a.inventory_id,
                "type_name": a.inventory.type.name if a.inventory_id else "",
                "name": a.name,
                "count": a.count,
                "price": float(a.unit_price),
                "amount": a.amount,
                "image": a.image_id,
                "thumbnail": _thumbnail(a.image) if a.image_id else None,
            }
            for a in obj.accessories.all()
        ]


class RoomTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = RoomType
        fields = ["id", "name", "icon", "ordering", "object_types"]


def _room_image(img):
    from ..views.files import _thumbnail

    f = img.file
    return {
        "id": img.id,
        "file": f.pk,
        "calculate": img.calculate_id,
        "name": f.original_filename or f.label or "",
        "thumbnail": _thumbnail(f),
    }


class RoomSerializer(serializers.ModelSerializer):
    room_type_name = serializers.CharField(source="room_type.name", read_only=True)
    icon = serializers.CharField(source="room_type.icon", read_only=True)
    images = serializers.SerializerMethodField()

    class Meta:
        model = Room
        fields = ["id", "name", "room_type", "room_type_name", "icon", "ordering", "images"]

    def get_images(self, obj):
        return [_room_image(i) for i in obj.images.all()]


class RoomInputSerializer(serializers.Serializer):
    room_type = serializers.PrimaryKeyRelatedField(queryset=RoomType.objects.all())
    name = serializers.CharField(max_length=255, required=False, allow_blank=True)


class CalculationItemInputSerializer(serializers.Serializer):
    inventory_type = serializers.IntegerField()
    inventory = serializers.IntegerField(required=False, allow_null=True)
    count = serializers.FloatField(required=False, allow_null=True, min_value=0)


class AccessoryInputSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False, allow_null=True)
    inventory = serializers.IntegerField(required=False, allow_null=True)
    name = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    count = serializers.FloatField(min_value=0, required=False, default=1)
    price = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=0, required=False, allow_null=True
    )
    image = serializers.IntegerField(required=False, allow_null=True)


class CalculationInputSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    count = serializers.FloatField(min_value=0)
    object_type = serializers.PrimaryKeyRelatedField(queryset=ObjectType.objects.all())
    items = CalculationItemInputSerializer(many=True, required=False)
    room = serializers.IntegerField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True, default="")
    color = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    manual_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=0, required=False, allow_null=True, default=None
    )
    accessories = AccessoryInputSerializer(many=True, required=False, default=list)
    unit = serializers.ChoiceField(choices=["", "kv", "pog"], required=False, default="")
    height = serializers.IntegerField(
        min_value=0, max_value=100000, required=False, allow_null=True
    )
    width = serializers.IntegerField(min_value=0, max_value=100000, required=False, allow_null=True)
    depth = serializers.IntegerField(min_value=0, max_value=100000, required=False, allow_null=True)


class PriceSerializer(OfferFieldsMixin, serializers.ModelSerializer):
    kind = "price"
    metering = MeteringShortSerializer(read_only=True)
    user_detail = UserShortSerializer(source="user", read_only=True)
    price = MoneyField(read_only=True)
    order = serializers.SerializerMethodField()

    class Meta:
        model = Price
        fields = [
            "id",
            "metering",
            "price",
            "done",
            "desc",
            "created_at",
            "folder",
            "user_detail",
            "order",
            "client_title",
            "variant",
            "duration_days",
            *OfferFieldsMixin.OFFER_FIELDS,
        ]
        # the stage-2 state moves only through the services (finish / done / due / answer)
        read_only_fields = [
            "metering",
            "price",
            "done",
            "created_at",
            "folder",
            "duration_days",
            *OfferFieldsMixin.OFFER_FIELDS,
        ]

    def get_order(self, obj):
        return _order_summary(obj.metering, self.context)


class PriceDetailSerializer(PriceSerializer):
    calculations = serializers.SerializerMethodField()
    rooms = serializers.SerializerMethodField()
    sheet = serializers.SerializerMethodField()
    actions = serializers.SerializerMethodField()
    answers = serializers.SerializerMethodField()

    class Meta(PriceSerializer.Meta):
        fields = PriceSerializer.Meta.fields + [
            "calculations",
            "rooms",
            "sheet",
            "versions",
            "locked",
            "actions",
            "answers",
        ]

    def get_answers(self, obj):
        if obj.metering is None:
            return []
        rows = [a for a in obj.metering.offer_answers.all() if a.kind == "price"]
        return OfferAnswerSerializer(rows, many=True).data

    versions = serializers.SerializerMethodField()
    locked = serializers.SerializerMethodField()

    def get_locked(self, obj):
        from metering.price.services import price_locked

        if not hasattr(self, "_locked"):
            self._locked = price_locked(obj)
        return self._locked

    def get_versions(self, obj):
        return [
            {
                "id": v.id,
                "number": v.number,
                "label": v.label,
                "total": float(v.total),
                "created_at": v.created_at,
                "created_by": (
                    (v.created_by.name or str(v.created_by.phone)) if v.created_by else None
                ),
            }
            for v in obj.versions.select_related("created_by").order_by("-number")
        ]

    def get_rooms(self, obj):
        qs = (
            Room.objects.filter(price=obj)
            .select_related("room_type")
            .prefetch_related("images__file")
        )
        return RoomSerializer(qs, many=True).data

    def get_sheet(self, obj):
        """The offer exactly as the Excel/PDF print it (the page's «Excel» view)."""
        from metering.price.services import offer_data, offer_lines

        data = offer_data(obj)
        for r in data["rooms"]:
            r["images"] = len(r["images"])
            for it in r["items"]:
                it["lines"] = offer_lines(it)
                it["images"] = len(it["images"])
                for a in it["accessories"]:
                    a["image"] = a["image"].pk if a["image"] else None
        return data

    def get_calculations(self, obj):
        qs = (
            Calculate.objects.filter(price=obj)
            .select_related("obj")
            .prefetch_related(
                "inventoryincalculate_set__inventory__type",
                "accessories__image",
                "accessories__inventory__type",
            )
            .order_by("id")
        )
        return CalculationSerializer(qs, many=True, context=self.context).data

    def get_actions(self, obj):
        user = self.context["request"].user
        can_change = user.has_perm("price.change_price")
        return {
            "edit": can_change
            and user.has_perms(["price.add_calculate", "price.change_calculate"])
            and not self.get_locked(obj),
            **_offer_actions(user, obj, "price"),
        }


class AssignTasksSerializer(serializers.Serializer):
    designer = serializers.IntegerField(required=False, allow_null=True)
    pricer = serializers.IntegerField(required=False, allow_null=True)
