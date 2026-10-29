from phonenumber_field.serializerfields import PhoneNumberField
from rest_framework import serializers

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
from metering.services import ASSIGNABLE_STATUSES, metering_is_editable
from oauth.constants import METERING_PERMISSION

from .. import i18n as uz
from ..fields import MoneyField
from .common import (
    ClientShortSerializer,
    OrderSummarySerializer,
    UserShortSerializer,
    order_of,
)


def _user(user):
    return UserShortSerializer(user).data if user is not None else None


def can_assign_tasks(user) -> bool:
    """The metering staff (who press "Замер выполнен") or whoever may edit meterings."""
    return user.has_perm(f"oauth.{METERING_PERMISSION}") or user.has_perm(
        "metering.change_metering"
    )


def _order_summary(metering, context):
    order = order_of(metering)
    return OrderSummarySerializer(order, context=context).data if order else None


class MeteringShortSerializer(serializers.ModelSerializer):
    client = ClientShortSerializer(read_only=True)

    class Meta:
        model = Metering
        fields = ["id", "client", "address", "address_link", "date_time", "status", "folder"]


class MeteringSerializer(serializers.ModelSerializer):
    client = ClientShortSerializer(read_only=True)
    status_label = serializers.SerializerMethodField()
    design = serializers.SerializerMethodField()
    price = serializers.SerializerMethodField()
    order = serializers.SerializerMethodField()
    is_editable = serializers.SerializerMethodField()

    class Meta:
        model = Metering
        fields = [
            "id",
            "client",
            "status",
            "status_label",
            "date_time",
            "address",
            "address_link",
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
        }

    def get_price(self, obj):
        price = getattr(obj, "price", None)
        if price is None:
            return None
        return {"id": price.pk, "done": price.done, "user": _user(price.user)}

    def get_order(self, obj):
        return _order_summary(obj, self.context)

    def get_is_editable(self, obj):
        return metering_is_editable(obj)


class MeteringDetailSerializer(MeteringSerializer):
    actions = serializers.SerializerMethodField()

    class Meta(MeteringSerializer.Meta):
        fields = MeteringSerializer.Meta.fields + ["actions"]
        read_only_fields = fields

    def get_actions(self, obj):
        """Which buttons this user gets — the admin's has_*_permission checks."""
        user = self.context["request"].user
        status = obj.status
        S = MeteringStatus
        can_change = user.has_perm("metering.change_metering")
        return {
            "edit": can_change and metering_is_editable(obj),
            "dont_need": can_change and status in [S.created, S.other_day, S.metering_done],
            "other_day": can_change and status in [S.created, S.other_day],
            "metering_done": user.has_perm(f"oauth.{METERING_PERMISSION}")
            and status in [S.created, S.other_day],
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


class MeteringCreateSerializer(serializers.Serializer):
    client_phone = PhoneNumberField(region="UZ")
    client_fio = serializers.CharField(max_length=255, required=False, allow_blank=True)
    date_time = serializers.DateTimeField()
    address = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    address_link = serializers.URLField(
        max_length=1000, required=False, allow_blank=True, allow_null=True
    )
    desc = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    invoice = serializers.IntegerField(required=False, allow_null=True)


class MeteringUpdateSerializer(serializers.ModelSerializer):
    """MeteringAdmin leaves only date_time and desc editable on an existing row."""

    class Meta:
        model = Metering
        fields = ["date_time", "desc"]


class OtherDaySerializer(serializers.Serializer):
    date_time = serializers.DateTimeField(required=False, allow_null=True)


# --- Design ---------------------------------------------------------------------


class DesignTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = DesignType
        fields = ["id", "name", "folder", "created_at"]
        read_only_fields = ["folder", "created_at"]


class DesignSerializer(serializers.ModelSerializer):
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
        ]
        read_only_fields = fields

    def get_order(self, obj):
        return _order_summary(obj.metering, self.context)

    def get_actions(self, obj):
        user = self.context["request"].user
        return {
            "done": user.has_perm("design.change_design") and not obj.done,
            "add_type": user.has_perm("design.add_designtype"),
            # can_create_order(), minus its query: metering__order is select_related.
            "create_order": user.has_perm("order.add_order")
            and obj.done
            and order_of(obj.metering) is None,
        }


# --- Price ----------------------------------------------------------------------


class ObjectTypeSerializer(serializers.ModelSerializer):
    count_label = serializers.SerializerMethodField()

    def get_count_label(self, obj):
        return uz.COUNT_NAME.get(obj.count_name, obj.get_count_name_display())

    class Meta:
        model = ObjectType
        fields = ["id", "name", "count_name", "count_label"]


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

    class Meta:
        model = Calculate
        fields = ["id", "name", "count", "obj", "room", "note", "amount", "items"]


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


class CalculationInputSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    count = serializers.FloatField(min_value=0)
    object_type = serializers.PrimaryKeyRelatedField(queryset=ObjectType.objects.all())
    items = CalculationItemInputSerializer(many=True, required=False)
    room = serializers.IntegerField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True, default="")


class PriceSerializer(serializers.ModelSerializer):
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
        ]
        read_only_fields = ["metering", "price", "done", "created_at", "folder"]

    def get_order(self, obj):
        return _order_summary(obj.metering, self.context)


class PriceDetailSerializer(PriceSerializer):
    calculations = serializers.SerializerMethodField()
    rooms = serializers.SerializerMethodField()
    sheet = serializers.SerializerMethodField()
    actions = serializers.SerializerMethodField()

    class Meta(PriceSerializer.Meta):
        fields = PriceSerializer.Meta.fields + ["calculations", "rooms", "sheet", "actions"]

    def get_rooms(self, obj):
        qs = (
            Room.objects.filter(price=obj)
            .select_related("room_type")
            .prefetch_related("images__file")
        )
        return RoomSerializer(qs, many=True).data

    def get_sheet(self, obj):
        """The offer exactly as the Excel/PDF print it (the page's «Excel» view)."""
        from metering.price.services import offer_data

        data = offer_data(obj)
        for r in data["rooms"]:
            r["images"] = len(r["images"])
        return data

    def get_calculations(self, obj):
        qs = (
            Calculate.objects.filter(price=obj)
            .select_related("obj")
            .prefetch_related("inventoryincalculate_set__inventory__type")
            .order_by("id")
        )
        return CalculationSerializer(qs, many=True, context=self.context).data

    def get_actions(self, obj):
        user = self.context["request"].user
        can_change = user.has_perm("price.change_price")
        return {
            "edit": can_change
            and user.has_perms(["price.add_calculate", "price.change_calculate"]),
            "done": can_change and not obj.done,
        }


class AssignTasksSerializer(serializers.Serializer):
    designer = serializers.IntegerField(required=False, allow_null=True)
    pricer = serializers.IntegerField(required=False, allow_null=True)
