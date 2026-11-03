from phonenumber_field.serializerfields import PhoneNumberField
from rest_framework import serializers

from client.models import Client
from oauth.models import User
from order.constants import ORDER_VIEW_PRICE_PERMISSION

from .. import i18n as uz
from ..fields import MoneyField
from ..utils import order_deadline


def can_view_price(request) -> bool:
    return bool(request and request.user.has_perm(f"order.{ORDER_VIEW_PRICE_PERMISSION}"))


def map_url(obj) -> str | None:
    """Where "open on the map" goes for a lead / metering / order (core.geo.yandex_url)."""
    from core.geo import obj_map_url

    return obj_map_url(obj)


class LocationFieldsMixin(serializers.Serializer):
    """Read-only `lat`, `lon` (6-place strings or null) and `map_url` for a model that
    has the location columns."""

    lat = serializers.SerializerMethodField()
    lon = serializers.SerializerMethodField()
    map_url = serializers.SerializerMethodField()

    def get_lat(self, obj):
        from core.geo import coord_str

        return coord_str(obj.lat)

    def get_lon(self, obj):
        from core.geo import coord_str

        return coord_str(obj.lon)

    def get_map_url(self, obj):
        return map_url(obj)


class LocationInputMixin(serializers.Serializer):
    """`location` (a link or coordinates) -> lat / lon / address_link in validated data.
    The legacy `address_link` input is read as a location too (kept as is when it is
    not a recognisable map link)."""

    location = serializers.CharField(required=False, allow_blank=True, max_length=2000)

    def validate(self, attrs):
        from core.exceptions import ServiceError
        from core.geo import location_input

        attrs = super().validate(attrs)
        text = attrs.pop("location", None)
        legacy = text is None and attrs.get("address_link")
        if text is None and not legacy:
            return attrs
        try:
            point, link, _short = location_input(
                text if text is not None else attrs["address_link"]
            )
        except ServiceError as e:
            if legacy:
                return attrs
            raise serializers.ValidationError({"location": e.message})
        attrs["lat"] = point.lat if point else None
        attrs["lon"] = point.lon if point else None
        attrs["address_link"] = link
        return attrs


class LocationSetSerializer(serializers.Serializer):
    """Body of POST /{invoices|meterings|orders}/{id}/location/."""

    location = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    address = serializers.CharField(required=False, allow_blank=True, max_length=255)

    def validate(self, attrs):
        from core.exceptions import ServiceError
        from core.geo import UNSET, location_input

        if "location" not in attrs:
            # no `location` key: keep the stored point and link, update the address only
            attrs["point"], attrs["link"], attrs["short"] = UNSET, UNSET, False
            return attrs
        try:
            point, link, short = location_input(attrs["location"])
        except ServiceError as e:
            raise serializers.ValidationError({"location": e.message})
        attrs["point"], attrs["link"], attrs["short"] = point, link, short
        return attrs


class UserShortSerializer(serializers.ModelSerializer):
    phone = PhoneNumberField(region="UZ", read_only=True)

    class Meta:
        model = User
        fields = ["id", "name", "phone"]


class ClientShortSerializer(serializers.ModelSerializer):
    phone = PhoneNumberField(region="UZ", read_only=True)

    class Meta:
        model = Client
        fields = ["phone", "fio"]


class OrderSummarySerializer(serializers.Serializer):
    """The order columns the admin repeats on Metering/Design/Price/production lists:
    number, status, days left (and money left, for users who may see prices)."""

    id = serializers.IntegerField()
    order_number = serializers.IntegerField()
    status = serializers.CharField()
    status_label = serializers.SerializerMethodField()
    deadline = serializers.SerializerMethodField()
    money_left = serializers.SerializerMethodField()

    def get_status_label(self, order):
        return uz.order_status(order.status)

    def get_deadline(self, order):
        return order_deadline(order)

    def get_money_left(self, order):
        if not can_view_price(self.context.get("request")):
            return None
        return money_left(order)


def money_left(order):
    """Mirrors order_money_left_display, but returns None instead of "-"."""
    if order.price is None or order.price.amount is None:
        return None
    total = order.total_price
    if order.lost_money is None or order.lost_money.amount is None:
        return MoneyField().to_representation(total)
    if total.currency != order.lost_money.currency:
        return None
    return MoneyField().to_representation(total - order.lost_money)


def order_of(obj):
    """Reverse OneToOne to Order (from a Metering), or None when there is none."""
    if obj is None:
        return None
    from order.models import Order

    try:
        return obj.order
    except Order.DoesNotExist:
        return None
