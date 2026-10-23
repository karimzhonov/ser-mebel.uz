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
)
from metering.services import metering_is_editable
from oauth.constants import METERING_PERMISSION

from ..fields import MoneyField
from .common import ClientShortSerializer, OrderSummarySerializer, order_of


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
        return MeteringStatus(obj.status).label

    def get_design(self, obj):
        design = getattr(obj, "design", None)
        return {"id": design.pk, "done": design.done, "confirm": design.confirm} if design else None

    def get_price(self, obj):
        price = getattr(obj, "price", None)
        return {"id": price.pk, "done": price.done} if price else None

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
    order = serializers.SerializerMethodField()
    types = DesignTypeSerializer(source="designtype_set", many=True, read_only=True)
    actions = serializers.SerializerMethodField()

    class Meta:
        model = Design
        fields = ["id", "metering", "created_at", "done", "confirm", "types", "order", "actions"]
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
    count_label = serializers.CharField(source="get_count_name_display", read_only=True)

    class Meta:
        model = ObjectType
        fields = ["id", "name", "count_name", "count_label"]


class InventorySerializer(serializers.ModelSerializer):
    price = MoneyField(allow_null=True, required=False)

    class Meta:
        model = Inventory
        fields = ["id", "name", "type", "price"]


class InventoryTypeSerializer(serializers.ModelSerializer):
    type_label = serializers.CharField(source="get_type_display", read_only=True)
    inventories = InventorySerializer(source="inventory_set", many=True, read_only=True)

    class Meta:
        model = InventoryType
        fields = ["id", "name", "obj", "type", "type_label", "ordering", "inventories"]


class CalculationItemSerializer(serializers.ModelSerializer):
    inventory_type = serializers.IntegerField(source="inventory.type_id", read_only=True)
    inventory_name = serializers.CharField(source="inventory.name", read_only=True)
    price = MoneyField(read_only=True)

    class Meta:
        model = InventoryInCalculate
        fields = ["id", "inventory_type", "inventory", "inventory_name", "count", "price"]


class CalculationSerializer(serializers.ModelSerializer):
    amount = MoneyField(read_only=True)
    items = CalculationItemSerializer(source="inventoryincalculate_set", many=True, read_only=True)

    class Meta:
        model = Calculate
        fields = ["id", "name", "count", "obj", "amount", "items"]


class CalculationItemInputSerializer(serializers.Serializer):
    inventory_type = serializers.IntegerField()
    inventory = serializers.IntegerField(required=False, allow_null=True)
    count = serializers.FloatField(required=False, allow_null=True, min_value=0)


class CalculationInputSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    count = serializers.FloatField(min_value=0)
    object_type = serializers.PrimaryKeyRelatedField(queryset=ObjectType.objects.all())
    items = CalculationItemInputSerializer(many=True, required=False)


class PriceSerializer(serializers.ModelSerializer):
    metering = MeteringShortSerializer(read_only=True)
    price = MoneyField(read_only=True)
    order = serializers.SerializerMethodField()

    class Meta:
        model = Price
        fields = ["id", "metering", "price", "done", "desc", "created_at", "folder", "order"]
        read_only_fields = ["metering", "price", "done", "created_at", "folder"]

    def get_order(self, obj):
        return _order_summary(obj.metering, self.context)


class PriceDetailSerializer(PriceSerializer):
    calculations = serializers.SerializerMethodField()
    actions = serializers.SerializerMethodField()

    class Meta(PriceSerializer.Meta):
        fields = PriceSerializer.Meta.fields + ["calculations", "actions"]

    def get_calculations(self, obj):
        qs = (
            Calculate.objects.filter(price=obj)
            .select_related("obj")
            .prefetch_related("inventoryincalculate_set__inventory")
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
