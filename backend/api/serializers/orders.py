from phonenumber_field.serializerfields import PhoneNumberField
from rest_framework import serializers

from accounting.models import EXPENSE_ORDER_PERMISSION
from metering.design.models import DesignType
from metering.models import Metering
from oauth.models import User
from order.assembly.constants import ASSEMBLY_MANAGER_PERMISSION
from order.assembly.models import Assembly
from order.constants import ORDER_CHANGE_STATUS_PERMISSION, OrderStatus
from order.detailing.models import Detailing
from order.models import Factory, Order
from order.painter.models import Painter, PainterType
from order.rover.models import Rover

from ..fields import MoneyField
from ..utils import order_deadline
from .common import ClientShortSerializer, UserShortSerializer, can_view_price, money_left

PRICE_FIELDS = ["price", "lost_money", "discount", "total_price", "money_left"]


class FactorySerializer(serializers.ModelSerializer):
    phone = PhoneNumberField(region="UZ", required=False, allow_blank=True)

    class Meta:
        model = Factory
        fields = ["id", "name", "address", "phone", "ordering"]


class OrderSerializer(serializers.ModelSerializer):
    client = ClientShortSerializer(read_only=True)
    factory = FactorySerializer(read_only=True)
    status_label = serializers.SerializerMethodField()
    deadline = serializers.SerializerMethodField()
    price = MoneyField(read_only=True)
    lost_money = MoneyField(read_only=True)
    total_price = serializers.SerializerMethodField()
    money_left = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id",
            "order_number",
            "client",
            "factory",
            "address",
            "address_link",
            "desc",
            "status",
            "status_label",
            "reception_date",
            "end_date",
            "deadline",
            "metering",
            "folder",
            *PRICE_FIELDS,
        ]
        read_only_fields = fields

    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Same rule as OrderAdmin.get_fieldsets: money is only for view_order_price.
        if not can_view_price(self.context.get("request")):
            for field in PRICE_FIELDS:
                data.pop(field, None)
        return data

    def get_status_label(self, obj):
        return OrderStatus(obj.status).label

    def get_deadline(self, obj):
        return order_deadline(obj)

    def get_total_price(self, obj):
        if obj.price is None or obj.price.amount is None:
            return None
        return MoneyField().to_representation(obj.total_price)

    def get_money_left(self, obj):
        return money_left(obj)


def _production_row(obj, **extra):
    if obj is None:
        return None
    row = {"id": obj.pk, "done": obj.done, "square": obj.square, "folder": obj.folder_id}
    row.update(extra)
    return row


class OrderDetailSerializer(OrderSerializer):
    design_type = serializers.SerializerMethodField()
    production = serializers.SerializerMethodField()
    actions = serializers.SerializerMethodField()

    class Meta(OrderSerializer.Meta):
        fields = OrderSerializer.Meta.fields + ["design_type", "production", "actions"]
        read_only_fields = fields

    def get_design_type(self, obj):
        dt = obj.design_type
        return {"id": dt.pk, "name": dt.name, "folder": dt.folder_id} if dt else None

    def get_production(self, obj):
        show_price = can_view_price(self.context.get("request"))
        money = MoneyField().to_representation
        detailing = getattr(obj, "detailing", None)
        rover = getattr(obj, "rover", None)
        painter = getattr(obj, "painter", None)
        assembly = getattr(obj, "assembly", None)
        return {
            "detailing": (
                {
                    "id": detailing.pk,
                    "done": detailing.done,
                    "working_done": detailing.working_done,
                    "square": detailing.square,
                    "painter_square": detailing.painter_square,
                    "rover_square": detailing.rover_square,
                    "folder": detailing.folder_id,
                }
                if detailing
                else None
            ),
            "rover": _production_row(
                rover, price=money(rover.price) if rover and show_price else None
            ),
            "painter": _production_row(
                painter,
                type=painter.type.name if painter and painter.type else None,
                price=money(painter.price) if painter and show_price else None,
            ),
            "assembly": _production_row(
                assembly,
                installing_done=assembly.installing_done if assembly else None,
                user=(
                    UserShortSerializer(assembly.user).data if assembly and assembly.user else None
                ),
                price=money(assembly.price) if assembly and show_price else None,
            ),
        }

    def get_actions(self, obj):
        user = self.context["request"].user
        return {
            "edit": user.has_perm("order.change_order"),
            "detailing": user.has_perm("detailing.add_detailing")
            and obj.status == OrderStatus.CREATED,
            "next_status": user.has_perm(f"order.{ORDER_CHANGE_STATUS_PERMISSION}")
            and OrderStatus.next_status(obj.status) is not None,
            "next_status_label": (
                OrderStatus.next_status(obj.status).label
                if OrderStatus.next_status(obj.status)
                else None
            ),
            "go_to_assembly": user.has_perm(f"assembly.{ASSEMBLY_MANAGER_PERMISSION}")
            and obj.status == OrderStatus.WORKING,
            "add_expense": user.has_perm(f"accounting.{EXPENSE_ORDER_PERMISSION}"),
            "edit_price": can_view_price(self.context.get("request")),
        }


class OrderCreateSerializer(serializers.Serializer):
    client_phone = PhoneNumberField(region="UZ", required=False)
    client_fio = serializers.CharField(max_length=255, required=False, allow_blank=True)
    metering = serializers.PrimaryKeyRelatedField(
        queryset=Metering.objects.all(), required=False, allow_null=True
    )
    design_type = serializers.PrimaryKeyRelatedField(
        queryset=DesignType.objects.all(), required=False, allow_null=True
    )
    factory = serializers.PrimaryKeyRelatedField(
        queryset=Factory.objects.all(), required=False, allow_null=True
    )
    desc = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    reception_date = serializers.DateField(required=False)
    count_days = serializers.IntegerField(
        min_value=1, max_value=365, required=False, allow_null=True
    )
    address = serializers.CharField(max_length=255)
    address_link = serializers.URLField(
        max_length=1000, required=False, allow_blank=True, allow_null=True
    )
    price = MoneyField(required=False, allow_null=True)
    lost_money = MoneyField(required=False, allow_null=True)
    discount = serializers.FloatField(required=False, min_value=0, max_value=100)

    def validate(self, attrs):
        if not attrs.get("metering") and not attrs.get("client_phone"):
            raise serializers.ValidationError({"client_phone": "Мижоз телефонини киритинг."})
        return attrs


class OrderUpdateSerializer(serializers.ModelSerializer):
    """Fields OrderAdmin leaves editable on an existing order. Money fields are
    dropped by the view for users without view_order_price."""

    price = MoneyField(required=False, allow_null=True)
    lost_money = MoneyField(required=False, allow_null=True)

    class Meta:
        model = Order
        fields = [
            "order_number",
            "factory",
            "desc",
            "reception_date",
            "end_date",
            "price",
            "lost_money",
            "discount",
        ]

    def validate_order_number(self, value):
        qs = Order.objects.filter(order_number=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("Бундай рақамли заказ бор.")
        return value


# --- Production -----------------------------------------------------------------


class ProductionOrderSerializer(OrderSerializer):
    """The order block shown on every production row (no money: the production
    lists in the admin never show the order's price)."""

    class Meta(OrderSerializer.Meta):
        fields = [
            "id",
            "order_number",
            "client",
            "address",
            "address_link",
            "status",
            "status_label",
            "deadline",
            "end_date",
            "folder",
        ]
        read_only_fields = fields


class DetailingSerializer(serializers.ModelSerializer):
    order = ProductionOrderSerializer(read_only=True)
    actions = serializers.SerializerMethodField()

    class Meta:
        model = Detailing
        fields = [
            "id",
            "order",
            "created_at",
            "done",
            "working_done",
            "square",
            "painter_square",
            "rover_square",
            "folder",
            "actions",
        ]
        read_only_fields = ["order", "created_at", "done", "working_done", "folder"]

    def get_actions(self, obj):
        user = self.context["request"].user
        can_change = user.has_perm("detailing.change_detailing")
        return {"edit": can_change, "done": can_change and not obj.done}


class RoverSerializer(serializers.ModelSerializer):
    order = ProductionOrderSerializer(read_only=True)
    price = MoneyField(read_only=True)
    actions = serializers.SerializerMethodField()

    class Meta:
        model = Rover
        fields = ["id", "order", "created_at", "done", "square", "price", "folder", "actions"]
        read_only_fields = fields

    def get_actions(self, obj):
        user = self.context["request"].user
        return {"done": user.has_perm("rover.change_rover") and not obj.done}


class PainterTypeSerializer(serializers.ModelSerializer):
    price = MoneyField()
    user_detail = UserShortSerializer(source="user", read_only=True)

    class Meta:
        model = PainterType
        fields = ["id", "name", "price", "user", "user_detail"]


class PainterSerializer(serializers.ModelSerializer):
    order = ProductionOrderSerializer(read_only=True)
    price = MoneyField(read_only=True)
    type_detail = serializers.SerializerMethodField()
    actions = serializers.SerializerMethodField()

    class Meta:
        model = Painter
        fields = [
            "id",
            "order",
            "created_at",
            "done",
            "type",
            "type_detail",
            "square",
            "price",
            "folder",
            "actions",
        ]
        read_only_fields = ["order", "created_at", "done", "square", "price", "folder"]

    def get_type_detail(self, obj):
        return {"id": obj.type.pk, "name": obj.type.name} if obj.type else None

    def get_actions(self, obj):
        user = self.context["request"].user
        return {
            "edit": user.has_perm(f"assembly.{ASSEMBLY_MANAGER_PERMISSION}"),
            "done": user.has_perm("painter.change_painter") and not obj.done,
        }


class AssemblySerializer(serializers.ModelSerializer):
    order = ProductionOrderSerializer(read_only=True)
    price = MoneyField(read_only=True)
    user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), required=False, allow_null=True
    )
    user_detail = UserShortSerializer(source="user", read_only=True)
    actions = serializers.SerializerMethodField()

    class Meta:
        model = Assembly
        fields = [
            "id",
            "order",
            "created_at",
            "done",
            "installing_done",
            "user",
            "user_detail",
            "square",
            "price",
            "folder",
            "actions",
        ]
        read_only_fields = [
            "order",
            "created_at",
            "done",
            "installing_done",
            "square",
            "price",
            "folder",
        ]

    def get_actions(self, obj):
        user = self.context["request"].user
        can_change = user.has_perm("assembly.change_assembly")
        return {
            "edit": user.has_perm(f"assembly.{ASSEMBLY_MANAGER_PERMISSION}"),
            "done": can_change and not obj.done,
            "installing_done": can_change and obj.done and not obj.installing_done,
        }
