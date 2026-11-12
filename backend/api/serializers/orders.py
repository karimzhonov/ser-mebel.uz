from djmoney.money import Money
from phonenumber_field.serializerfields import PhoneNumberField
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from metering.design.models import DesignType
from metering.models import Metering
from oauth.models import User
from order.assembly.models import Assembly
from order.constants import ORDER_CHANGE_STATUS_PERMISSION, OrderStatus
from order.detailing.models import Detailing
from order.models import Factory, Order
from order.painter.models import Painter, PainterPart, PainterType
from order.painter.services import can_override_part
from order.rover.dto import design_folder_id
from order.rover.models import Rover
from order.services import (
    ASSEMBLY_SEND_MSG,
    INSTALLING_CONFIRM_MSG,
    can_send_to_assembly,
    installing_needs_head_confirm,
)
from order.visibility import sees_full_order, strip_order

from .. import i18n as uz
from ..fields import MoneyField
from ..utils import order_deadline
from .common import (
    ClientShortSerializer,
    LocationFieldsMixin,
    LocationInputMixin,
    UserShortSerializer,
    can_view_price,
    money_left,
)

PRICE_FIELDS = ["price", "lost_money", "discount", "total_price", "money_left"]


class FactorySerializer(serializers.ModelSerializer):
    phone = PhoneNumberField(region="UZ", required=False, allow_blank=True)

    class Meta:
        model = Factory
        fields = ["id", "name", "address", "phone", "ordering"]


class OrderSerializer(LocationFieldsMixin, serializers.ModelSerializer):
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
            "lat",
            "lon",
            "map_url",
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
        return uz.order_status(obj.status)

    def get_deadline(self, obj):
        return order_deadline(obj)

    def get_total_price(self, obj):
        if obj.price is None or obj.price.amount is None:
            return None
        return MoneyField().to_representation(obj.total_price)

    def get_money_left(self, obj):
        return money_left(obj)


def _painter_teams(painter):
    """«Team 10 m², Team 5 m²» or None (the order page's one-line summary)."""
    if painter is None:
        return None
    parts = list(painter.parts.all())
    return ", ".join(f"{x.type.name} {x.square:g} m²" for x in parts) or None


def _painter_parts(painter):
    if painter is None:
        return []
    return [{"type": x.type.name, "square": x.square, "done": x.done} for x in painter.parts.all()]


def _production_row(obj, **extra):
    if obj is None:
        return None
    row = {"id": obj.pk, "done": obj.done, "square": obj.square, "folder": obj.folder_id}
    row.update(extra)
    return row


class OrderDetailSerializer(OrderSerializer):
    calculation = serializers.SerializerMethodField()
    design_type = serializers.SerializerMethodField()
    production = serializers.SerializerMethodField()
    actions = serializers.SerializerMethodField()
    advance_pending = serializers.SerializerMethodField()

    class Meta(OrderSerializer.Meta):
        fields = OrderSerializer.Meta.fields + [
            "design_type",
            "production",
            "actions",
            "calculation",
            "advance_pending",
        ]
        read_only_fields = fields

    def get_advance_pending(self, obj):
        """The advance entered at creation, still waiting for the boss (None if none)."""
        a = obj.advances.filter(status="pending").first()
        if a is None:
            return None
        return {"id": a.pk, "amount": str(a.amount), "currency": a.currency}

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
                    "due_at": detailing.due_at,
                    "folder": detailing.folder_id,
                }
                if detailing
                else None
            ),
            "rover": _production_row(
                rover,
                state=rover.state if rover else None,
                price=money(rover.price) if rover and show_price else None,
            ),
            "painter": _production_row(
                painter,
                type=_painter_teams(painter),
                parts=_painter_parts(painter),
                waiting_rover=bool(rover and not rover.done),
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

    def get_calculation(self, obj):
        """The zamer's price calculation: {id, can_edit} for who may open it (owner's
        rule: after the order only the bosh menejer edits it), else null."""
        from metering.price.models import Price
        from metering.price.services import can_edit_price, can_view_price

        if obj.metering_id is None:
            return None
        price = Price.objects.filter(metering_id=obj.metering_id).first()
        user = self.context["request"].user
        if price is None or not can_view_price(user, price):
            return None
        return {"id": price.pk, "can_edit": can_edit_price(user, price)}

    def get_actions(self, obj):
        user = self.context["request"].user
        confirm_blocked = obj.status == OrderStatus.INSTALLING and installing_needs_head_confirm(
            obj
        )
        return {
            "edit": user.has_perm("order.change_order"),
            "detailing": user.has_perm("detailing.add_detailing")
            and obj.status == OrderStatus.CREATED,
            # «Yaratildi» → detailing only through «Detalirovkaga yuborish» (with a deadline)
            "next_status": user.has_perm(f"order.{ORDER_CHANGE_STATUS_PERMISSION}")
            and OrderStatus.next_status(obj.status)
            not in (
                None,
                OrderStatus.DETAILING,
                OrderStatus.ASSEMBLY,  # only via «Yig'ishga yuborish»
            )
            and not confirm_blocked,
            # «Установка» with an assembly: «Готов» only via the head's «Tayyor» (Yig'ish page)
            "next_status_hint": INSTALLING_CONFIRM_MSG if confirm_blocked else None,
            # «Xomashyo buyurtmasi» → «Сборка» is the production head's step
            "go_to_assembly_hint": (
                ASSEMBLY_SEND_MSG
                if obj.status == OrderStatus.WORKING and not can_send_to_assembly(user)
                else None
            ),
            "next_status_label": (
                uz.order_status(OrderStatus.next_status(obj.status))
                if OrderStatus.next_status(obj.status)
                else None
            ),
            "go_to_assembly": can_send_to_assembly(user) and obj.status == OrderStatus.WORKING,
            "finance": user.has_perm("accounting.view_all_operations"),
            "edit_price": can_view_price(self.context.get("request")),
        }


class OrderCreateSerializer(LocationInputMixin, serializers.Serializer):
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
    # may stay blank: it is then taken from the metering (order.services.create_order)
    address = serializers.CharField(max_length=255, required=False, allow_blank=True)
    address_link = serializers.URLField(
        max_length=1000, required=False, allow_blank=True, allow_null=True
    )
    price = MoneyField(required=False, allow_null=True)
    lost_money = MoneyField(required=False, allow_null=True)
    discount = serializers.FloatField(required=False, min_value=0, max_value=100)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if not attrs.get("metering") and not attrs.get("client_phone"):
            raise serializers.ValidationError({"client_phone": "Mijoz telefonini kiriting."})
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
            raise serializers.ValidationError("Bunday raqamli buyurtma bor.")
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
            "lat",
            "lon",
            "map_url",
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
            "due_at",
            "folder",
            "actions",
        ]
        read_only_fields = ["order", "created_at", "done", "working_done", "due_at", "folder"]

    def get_actions(self, obj):
        user = self.context["request"].user
        can_change = user.has_perm("detailing.change_detailing")
        return {
            "edit": can_change,
            "done": can_change and not obj.done,
            "due": user.has_perm("detailing.add_detailing") and not obj.done,
        }


class DetailingDueSerializer(serializers.Serializer):
    due_at = serializers.DateTimeField()


class RoverSerializer(serializers.ModelSerializer):
    order = ProductionOrderSerializer(read_only=True)
    design_folder = serializers.SerializerMethodField()
    price = MoneyField(read_only=True)
    state = serializers.CharField(read_only=True)
    state_label = serializers.CharField(read_only=True)
    submitted_by_detail = UserShortSerializer(source="submitted_by", read_only=True)
    checked_by_detail = UserShortSerializer(source="checked_by", read_only=True)
    due_set_by_detail = UserShortSerializer(source="due_set_by", read_only=True)
    overdue = serializers.BooleanField(read_only=True)
    actions = serializers.SerializerMethodField()

    class Meta:
        model = Rover
        fields = [
            "id",
            "order",
            "created_at",
            "done",
            "state",
            "state_label",
            "submitted_at",
            "submitted_by_detail",
            "checked_at",
            "checked_by_detail",
            "square",
            "price",
            "note",
            "due_date",
            "due_auto",
            "due_set_at",
            "due_set_by_detail",
            "overdue",
            "folder",
            "design_folder",
            "actions",
        ]
        read_only_fields = fields

    def get_design_folder(self, obj):
        restricted = not sees_full_order(self.context["request"].user)
        if hasattr(obj, "design_folder_pk"):  # annotated by RoverViewSet (no query per row)
            return obj.design_folder_pk or (None if restricted else obj.order.folder_id)
        return design_folder_id(obj.order, fallback=not restricted)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        restricted = not sees_full_order(self.context["request"].user)
        data["restricted"] = restricted
        data["can_open_order"] = not restricted
        if restricted:
            # the rover worker sees the design folder only
            strip_order(data["order"])
            data["folder"] = None
            if data["order"]:
                data["order"]["folder"] = None
        return data

    def get_actions(self, obj):
        user = self.context["request"].user
        return {
            "done": user.has_perm("rover.change_rover") and obj.state == "new",
            "confirm": user.has_perm("oauth.user_rover_checker") and obj.state == "checking",
            "due": user.has_perm("oauth.user_production_head") and obj.state != "done",
        }


class RoverDoneSerializer(serializers.Serializer):
    price = MoneyField()
    note = serializers.CharField(allow_blank=True, trim_whitespace=False)


class RoverDueSerializer(serializers.Serializer):
    due_date = serializers.DateField()


class PainterTypeSerializer(serializers.ModelSerializer):
    price = MoneyField()
    user_detail = UserShortSerializer(source="user", read_only=True)

    class Meta:
        model = PainterType
        fields = ["id", "name", "price", "user", "user_detail", "outsource"]

    def validate_outsource(self, value):
        # only the production head (and superusers) flag a team as outsource
        user = self.context["request"].user
        current = self.instance.outsource if self.instance is not None else False
        if value != current and not sees_full_order(user):
            raise PermissionDenied("Autsors belgisini faqat Ishlab chiqarish rahbari o'zgartiradi")
        return value


class PainterPartSerializer(serializers.ModelSerializer):
    """One team's share of a Molyar job."""

    price = MoneyField(read_only=True)
    type_detail = serializers.SerializerMethodField()
    painter_detail = serializers.SerializerMethodField()
    state = serializers.CharField(read_only=True)
    state_label = serializers.CharField(read_only=True)
    done_by_detail = UserShortSerializer(source="done_by", read_only=True)
    due_set_by_detail = UserShortSerializer(source="due_set_by", read_only=True)
    overdue = serializers.BooleanField(read_only=True)
    actions = serializers.SerializerMethodField()

    class Meta:
        model = PainterPart
        fields = [
            "id",
            "type",
            "type_detail",
            "painter_detail",
            "square",
            "price",
            "state",
            "state_label",
            "started_at",
            "due_date",
            "due_auto",
            "due_set_at",
            "due_set_by_detail",
            "overdue",
            "note",
            "done",
            "done_at",
            "done_by_detail",
            "actions",
        ]
        read_only_fields = fields

    def get_type_detail(self, obj):
        t = obj.type
        return {"id": t.pk, "name": t.name, "outsource": t.outsource}

    def get_painter_detail(self, obj):
        return UserShortSerializer(obj.user).data if obj.user else None

    def get_actions(self, obj):
        user = self.context["request"].user
        return {
            "done": bool(not obj.done and (can_override_part(user) or obj.type.user_id == user.pk)),
            "due": bool(not obj.done and user.has_perm("oauth.user_production_head")),
        }


class PainterSerializer(serializers.ModelSerializer):
    """The Molyar job. Heads/managers see every part and the whole square; a worker only
    their own parts (m², price, deadlines) - never other teams'."""

    order = ProductionOrderSerializer(read_only=True)
    design_folder = serializers.SerializerMethodField()
    price = serializers.SerializerMethodField()
    type = serializers.SerializerMethodField()
    type_detail = serializers.SerializerMethodField()
    painter_detail = serializers.SerializerMethodField()
    state = serializers.CharField(read_only=True)
    state_label = serializers.CharField(read_only=True)
    done_by_detail = UserShortSerializer(source="done_by", read_only=True)
    due_date = serializers.SerializerMethodField()
    due_auto = serializers.SerializerMethodField()
    due_set_at = serializers.SerializerMethodField()
    due_set_by_detail = serializers.SerializerMethodField()
    overdue = serializers.SerializerMethodField()
    note = serializers.SerializerMethodField()
    parts = serializers.SerializerMethodField()
    assigned_square = serializers.SerializerMethodField()
    remaining_square = serializers.SerializerMethodField()
    remainder = serializers.SerializerMethodField()
    parts_over = serializers.SerializerMethodField()
    actions = serializers.SerializerMethodField()

    class Meta:
        model = Painter
        fields = [
            "id",
            "order",
            "created_at",
            "done",
            "state",
            "state_label",
            "type",
            "type_detail",
            "painter_detail",
            "square",
            "assigned_square",
            "remaining_square",
            "remainder",
            "parts_over",
            "parts",
            "price",
            "note",
            "started_at",
            "done_at",
            "done_by_detail",
            "due_date",
            "due_auto",
            "due_set_at",
            "due_set_by_detail",
            "overdue",
            "folder",
            "design_folder",
            "actions",
        ]
        read_only_fields = fields

    # --- which parts the viewer sees -----------------------------------------------
    def _user(self):
        return self.context["request"].user

    def _full(self):
        return sees_full_order(self._user())

    def _all_parts(self, obj):
        return list(obj.parts.all())

    def _visible(self, obj):
        parts = self._all_parts(obj)
        if self._full():
            return parts
        uid = self._user().pk
        return [x for x in parts if x.type.user_id == uid]

    def _due_part(self, obj):
        """The part whose deadline stands for the job: the earliest open one with a date
        (else the latest finished one)."""
        vis = self._visible(obj)
        open_ = [x for x in vis if not x.done and x.due_date]
        if open_:
            return min(open_, key=lambda x: (x.due_date, x.pk))
        dated = [x for x in vis if x.due_date]
        return max(dated, key=lambda x: (x.due_date, x.pk)) if dated else None

    def _single(self, obj):
        vis = self._visible(obj)
        return vis[0] if len(vis) == 1 else None

    # --- fields --------------------------------------------------------------------
    def get_price(self, obj):
        if self._full():
            return MoneyField().to_representation(obj.price) if obj.price is not None else None
        prices = [x.price for x in self._visible(obj) if x.price is not None]
        if not prices:
            return None
        total = sum((m.amount for m in prices), 0)
        return MoneyField().to_representation(Money(total, prices[0].currency))

    def get_type(self, obj):
        x = self._single(obj)
        return x.type_id if x else None

    def get_type_detail(self, obj):
        x = self._single(obj)
        return {"id": x.type.pk, "name": x.type.name} if x else None

    def get_painter_detail(self, obj):
        x = self._single(obj)
        return UserShortSerializer(x.user).data if x and x.user else None

    def get_due_date(self, obj):
        x = self._due_part(obj)
        return x.due_date.isoformat() if x else None

    def get_due_auto(self, obj):
        x = self._due_part(obj)
        return bool(x and x.due_auto)

    def get_due_set_at(self, obj):
        x = self._due_part(obj)
        return (
            serializers.DateTimeField().to_representation(x.due_set_at)
            if x and x.due_set_at
            else None
        )

    def get_due_set_by_detail(self, obj):
        x = self._due_part(obj)
        return UserShortSerializer(x.due_set_by).data if x and x.due_set_by else None

    def get_overdue(self, obj):
        return any(x.overdue for x in self._visible(obj))

    def get_note(self, obj):
        x = self._single(obj)
        if x is not None:
            return x.note
        if self._full():
            return obj.note
        return "\n".join(f"{p.type.name}: {p.note}" for p in self._visible(obj) if p.note)

    def get_parts(self, obj):
        return PainterPartSerializer(self._visible(obj), many=True, context=self.context).data

    def get_assigned_square(self, obj):
        return round(sum(x.square for x in self._visible(obj)), 2)

    def get_remaining_square(self, obj):
        if not self._full():
            return None
        if obj.done:  # historical done jobs (no parts) have nothing left to give
            return 0.0
        return max(round(round(obj.square, 2) - self.get_assigned_square(obj), 2), 0.0)

    get_remainder = get_remaining_square

    def get_parts_over(self, obj):
        if not self._full():
            return False
        return self.get_assigned_square(obj) > round(obj.square, 2)

    def get_design_folder(self, obj):
        restricted = not sees_full_order(self.context["request"].user)
        if hasattr(obj, "design_folder_pk"):  # annotated by PainterViewSet (no query per row)
            return obj.design_folder_pk or (None if restricted else obj.order.folder_id)
        return design_folder_id(obj.order, fallback=not restricted)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if not self._full():
            vis = self._visible(instance)
            # a painter sees the design folder only (never the stage / order folders)
            data["folder"] = None
            if data["order"]:
                data["order"]["folder"] = None
            # and only their own m² / progress, not the job's
            data["square"] = data["assigned_square"]
            done = bool(vis) and all(x.done for x in vis)
            data["done"] = done
            data["state"] = "done" if done else "new"
            data["state_label"] = "Bajarildi" if done else "Ishda"
        # the client's contact is shown through a non-outsource part of the viewer's own
        restricted = not self._full() and not any(
            not x.type.outsource for x in self._visible(instance)
        )
        data["restricted"] = restricted
        data["can_open_order"] = not restricted
        if restricted:
            strip_order(data["order"])
        return data

    def get_actions(self, obj):
        user = self._user()
        head = user.has_perm("oauth.user_production_head")
        vis_open = [x for x in self._visible(obj) if not x.done]
        return {
            "edit": bool(head and not obj.done),
            "done": bool(
                vis_open
                and (can_override_part(user) or any(x.type.user_id == user.pk for x in vis_open))
            ),
            "due": bool(head and any(not x.done for x in self._all_parts(obj))),
        }


class PainterDoneSerializer(serializers.Serializer):
    note = serializers.CharField(allow_blank=True, trim_whitespace=False)
    part = serializers.IntegerField(required=False)


class PainterAssignSerializer(serializers.Serializer):
    type = serializers.IntegerField(allow_null=True)


class PainterPartRowSerializer(serializers.Serializer):
    id = serializers.IntegerField(allow_null=True, required=False)
    type = serializers.IntegerField()
    square = serializers.FloatField()


class PainterPartsSerializer(serializers.Serializer):
    parts = PainterPartRowSerializer(many=True, allow_empty=True, max_length=20)


class PainterDueSerializer(serializers.Serializer):
    due_date = serializers.DateField()
    part = serializers.IntegerField(required=False)


class AssemblySerializer(serializers.ModelSerializer):
    order = ProductionOrderSerializer(read_only=True)
    price = MoneyField(read_only=True)
    user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), required=False, allow_null=True
    )
    user_detail = UserShortSerializer(source="user", read_only=True)
    state = serializers.CharField(read_only=True)
    state_label = serializers.CharField(read_only=True)
    finished_by_detail = UserShortSerializer(source="finished_by", read_only=True)
    due_set_by_detail = UserShortSerializer(source="due_set_by", read_only=True)
    confirmed_by_detail = UserShortSerializer(source="confirmed_by", read_only=True)
    overdue = serializers.BooleanField(read_only=True)
    actions = serializers.SerializerMethodField()

    class Meta:
        model = Assembly
        fields = [
            "id",
            "order",
            "created_at",
            "done",
            "installing_done",
            "state",
            "state_label",
            "user",
            "user_detail",
            "square",
            "price",
            "note",
            "started_at",
            "finished_at",
            "finished_by_detail",
            "confirmed_at",
            "confirmed_by_detail",
            "due_date",
            "due_auto",
            "due_set_at",
            "due_set_by_detail",
            "overdue",
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
            "note",
            "started_at",
            "finished_at",
            "confirmed_at",
            "due_date",
            "due_auto",
            "due_set_at",
            "folder",
        ]

    def get_actions(self, obj):
        user = self.context["request"].user
        mine = user.has_perm("assembly.change_assembly") or obj.user_id == user.pk
        head = user.has_perm("oauth.user_production_head")
        return {
            "edit": bool(head and obj.finished_at is None and not obj.installing_done),
            "done": bool(mine and not obj.done),
            "installing_done": bool(
                mine and obj.done and obj.finished_at is None and not obj.installing_done
            ),
            "confirm": bool(head and obj.state == "checking"),
            "due": bool(head and obj.finished_at is None and not obj.installing_done),
        }


class AssemblyAssignSerializer(serializers.Serializer):
    user = serializers.IntegerField(allow_null=True)


class AssemblyFinishSerializer(serializers.Serializer):
    # a missing/blank note is refused by the service with {field: "note"}
    note = serializers.CharField(
        required=False, default="", allow_blank=True, trim_whitespace=False
    )


class AssemblyDueSerializer(serializers.Serializer):
    due_date = serializers.DateField()
