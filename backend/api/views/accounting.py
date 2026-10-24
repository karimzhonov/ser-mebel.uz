from django.db.models import F, Sum
from djmoney import settings as dj_settings
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from accounting.models import Expense, ExpenseCategory, Income, IncomeCategory

from ..permissions import ModelPermissions
from ..serializers.accounting import (
    ExpenseCategorySerializer,
    ExpenseSerializer,
    IncomeCategorySerializer,
    IncomeSerializer,
)
from ..utils import apply_period, int_param, timeseries


class _SuperuserEditsMixin:
    """IncomeAdmin/ExpenseAdmin (and their category admins): anyone with add_* may
    book, only a superuser may change or delete."""

    def check_object_permissions(self, request, obj):
        super().check_object_permissions(request, obj)
        if request.method in ("PATCH", "PUT", "DELETE") and not request.user.is_superuser:
            raise PermissionDenied("Таҳрирлаш фақат администратор учун.")


class _CategoryViewSet(_SuperuserEditsMixin, viewsets.ModelViewSet):
    permission_classes = [ModelPermissions]
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class IncomeCategoryViewSet(_CategoryViewSet):
    queryset = IncomeCategory.objects.order_by("name")
    serializer_class = IncomeCategorySerializer


class ExpenseCategoryViewSet(_CategoryViewSet):
    queryset = ExpenseCategory.objects.order_by("name")
    serializer_class = ExpenseCategorySerializer


class _MoneyViewSet(_SuperuserEditsMixin, viewsets.ModelViewSet):
    """Income / Expense. Non-superusers only see what they booked themselves.

    ?currency=USD|UZS converts every amount in /stats/ at the configured rate — the
    ConvertedCostManager annotation reads it from the request (core/djmoney.py).
    """

    permission_classes = [ModelPermissions]
    search_fields = ["desc", "category__name"]
    ordering_fields = ["created_at"]
    ordering = ["-created_at"]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    model = None
    extra_filters = ()

    def get_queryset(self):
        qs = self.model.objects.select_related("category", "user")
        if not self.request.user.is_superuser:
            qs = qs.filter(user=self.request.user)
        params = self.request.query_params
        for name in ("category", "user", *self.extra_filters):
            value = int_param(params, name)
            if value is not None:
                qs = qs.filter(**{f"{name}_id": value})
        return apply_period(qs, "created_at", params)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=False, methods=["get"])
    def stats(self, request):
        currency = request.query_params.get("currency") or dj_settings.DEFAULT_CURRENCY
        qs = self.filter_queryset(self.get_queryset())
        total = qs.aggregate(total=Sum("converted_cost"))["total"] or 0
        categories = (
            qs.order_by()
            .values("category")
            .annotate(label=F("category__name"), amount=Sum("converted_cost"))
            .order_by("-amount")
        )
        return Response(
            {
                "currency": currency,
                "total": round(float(total), 2),
                "count": qs.count(),
                "by_category": [
                    {
                        "id": row["category"],
                        "label": row["label"],
                        "amount": round(float(row["amount"] or 0), 2),
                        "share": float(row["amount"] or 0) / float(total) if total else 0,
                    }
                    for row in categories
                ],
                "timeline": timeseries(
                    qs,
                    "created_at",
                    request.query_params,
                    value=Sum("converted_cost"),
                ),
            }
        )


class IncomeViewSet(_MoneyViewSet):
    model = Income
    serializer_class = IncomeSerializer


class ExpenseViewSet(_MoneyViewSet):
    model = Expense
    serializer_class = ExpenseSerializer
    extra_filters = ("order",)

    def get_queryset(self):
        return super().get_queryset().select_related("order__client")
