from rest_framework import serializers

from accounting.models import Expense, ExpenseCategory, Income, IncomeCategory
from order.constants import OrderStatus
from order.models import Order

from ..fields import MoneyField
from .common import UserShortSerializer


class IncomeCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = IncomeCategory
        fields = ["id", "name", "created_at"]
        read_only_fields = ["created_at"]


class ExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseCategory
        fields = ["id", "name", "created_at"]
        read_only_fields = ["created_at"]


class IncomeSerializer(serializers.ModelSerializer):
    cost = MoneyField()
    user_detail = UserShortSerializer(source="user", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = Income
        fields = ["id", "cost", "category", "category_name", "desc", "created_at", "user_detail"]
        read_only_fields = ["created_at"]


class ExpenseSerializer(serializers.ModelSerializer):
    cost = MoneyField()
    user_detail = UserShortSerializer(source="user", read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)
    # ExpenseForm: an expense can only be booked on an order that is not finished.
    order = serializers.PrimaryKeyRelatedField(
        queryset=Order.objects.exclude(status=OrderStatus.DONE), required=False, allow_null=True
    )
    order_detail = serializers.SerializerMethodField()

    class Meta:
        model = Expense
        fields = [
            "id",
            "cost",
            "category",
            "category_name",
            "desc",
            "order",
            "order_detail",
            "created_at",
            "user_detail",
        ]
        read_only_fields = ["created_at"]

    def get_order_detail(self, obj):
        if not obj.order_id:
            return None
        return {
            "id": obj.order_id,
            "order_number": obj.order.order_number,
            "client": str(obj.order.client) if obj.order.client_id else None,
        }
