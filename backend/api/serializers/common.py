from phonenumber_field.serializerfields import PhoneNumberField
from rest_framework import serializers

from client.models import Client
from oauth.models import User
from order.constants import ORDER_VIEW_PRICE_PERMISSION, OrderStatus

from ..fields import MoneyField
from ..utils import order_deadline


def can_view_price(request) -> bool:
    return bool(request and request.user.has_perm(f"order.{ORDER_VIEW_PRICE_PERMISSION}"))


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
        return OrderStatus(order.status).label

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
