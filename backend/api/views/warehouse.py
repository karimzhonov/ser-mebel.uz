"""Ombor API. Reads need the warehouse.view_* permission; every write goes through
warehouse/services.py, which also requires the caller to be THE keeper (omborchi)."""

from __future__ import annotations

from django.http import HttpResponse
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from oauth.models import User
from warehouse import services as W
from warehouse.excel import build_xlsx
from warehouse.models import UNITS, Movement, Product, WarehouseConfig

from ..permissions import ModelPermissions, is_staff
from ..serializers.common import UserShortSerializer
from ..utils import date_range, int_param


class ProductSerializer(serializers.ModelSerializer):
    unit_label = serializers.CharField(source="get_unit_display", read_only=True)
    value = serializers.SerializerMethodField()
    low = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "code",
            "category",
            "unit",
            "unit_label",
            "min_quantity",
            "quantity",
            "avg_cost",
            "value",
            "low",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["quantity", "avg_cost", "created_at"]

    def get_value(self, obj):
        return round(float(obj.quantity * obj.avg_cost), 2)

    def get_low(self, obj):
        return bool(obj.min_quantity) and obj.quantity <= obj.min_quantity


class MovementSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_unit = serializers.CharField(source="product.get_unit_display", read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    order_number = serializers.IntegerField(
        source="order.order_number", read_only=True, default=None
    )
    created_by_detail = UserShortSerializer(source="created_by", read_only=True)

    class Meta:
        model = Movement
        fields = [
            "id",
            "number",
            "product",
            "product_name",
            "product_unit",
            "kind",
            "kind_label",
            "quantity",
            "unit_price",
            "total",
            "date",
            "counterparty",
            "order_number",
            "comment",
            "balance_after",
            "created_by_detail",
            "created_at",
            "is_cancelled",
            "cancelled_at",
        ]
        read_only_fields = fields


class MovementInputSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    kind = serializers.ChoiceField(choices=["in", "out"])
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3)
    unit_price = serializers.DecimalField(max_digits=16, decimal_places=2)
    date = serializers.DateField(required=False)
    counterparty = serializers.CharField(required=False, allow_blank=True, max_length=255)
    order_number = serializers.IntegerField(required=False, allow_null=True)
    comment = serializers.CharField(required=False, allow_blank=True)


class ProductViewSet(viewsets.ModelViewSet):
    permission_classes = [ModelPermissions]
    serializer_class = ProductSerializer
    search_fields = ["name", "code", "category"]
    ordering_fields = ["name", "quantity", "category"]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = Product.objects.all()
        p = self.request.query_params
        if p.get("active") in ("0", "1"):
            qs = qs.filter(is_active=p["active"] == "1")
        if p.get("category"):
            qs = qs.filter(category=p["category"])
        if p.get("low") == "1":
            from django.db.models import F

            qs = qs.filter(min_quantity__gt=0, quantity__lte=F("min_quantity"))
        return qs

    def create(self, request, *args, **kwargs):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        p = W.save_product(request.user, dict(s.validated_data))
        return Response(ProductSerializer(p).data, status=201)

    def partial_update(self, request, *args, **kwargs):
        p = self.get_object()
        s = self.get_serializer(p, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        p = W.save_product(request.user, dict(s.validated_data), p)
        return Response(ProductSerializer(p).data)

    def destroy(self, request, *args, **kwargs):
        W.delete_product(request.user, self.get_object())
        return Response(status=204)

    @action(detail=False, methods=["get"])
    def categories(self, request):
        cats = (
            Product.objects.exclude(category="")
            .values_list("category", flat=True)
            .distinct()
            .order_by("category")
        )
        return Response(
            {
                "categories": list(cats),
                "units": [{"value": v, "label": label} for v, label in UNITS],
            }
        )


class MovementViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    permission_classes = [ModelPermissions]
    serializer_class = MovementSerializer
    search_fields = ["product__name", "counterparty", "comment"]
    ordering_fields = ["number", "date"]

    def get_queryset(self):
        qs = Movement.objects.select_related("product", "order", "created_by")
        p = self.request.query_params
        start, end = date_range(p)
        if start:
            qs = qs.filter(date__gte=start)
        if end:
            qs = qs.filter(date__lte=end)
        if p.get("kind") in ("in", "out"):
            qs = qs.filter(kind=p["kind"])
        prod = int_param(p, "product")
        if prod:
            qs = qs.filter(product_id=prod)
        if self.action == "list" and p.get("cancelled") != "all":
            qs = qs.filter(is_cancelled=p.get("cancelled") == "1")
        return qs

    def create(self, request, *args, **kwargs):
        s = MovementInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        m = W.add_movement(
            request.user,
            product=d["product"],
            kind=d["kind"],
            quantity=d["quantity"],
            unit_price=d["unit_price"],
            on_date=d.get("date"),
            counterparty=d.get("counterparty", ""),
            order_number=d.get("order_number"),
            comment=d.get("comment", ""),
        )
        return Response(MovementSerializer(m).data, status=201)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        m = W.cancel_movement(request.user, self.get_object())
        return Response(MovementSerializer(m).data)


class WarehouseSummaryView(APIView):
    permission_classes = [ModelPermissions]
    queryset = Product.objects.none()

    def get(self, request):
        start, end = date_range(request.query_params)
        sm = W.summary(start, end)
        k = sm.pop("keeper")
        sm["keeper"] = UserShortSerializer(k).data if k else None
        sm["is_keeper"] = W.is_keeper(request.user)
        return Response(sm)


class KeeperView(APIView):
    """GET: who is the omborchi. PUT {user: id|null}: superuser assigns them."""

    queryset = WarehouseConfig.objects.none()

    def get(self, request):
        if not is_staff(request.user):
            raise PermissionDenied()
        k = W.keeper()
        return Response({"keeper": UserShortSerializer(k).data if k else None})

    def put(self, request):
        if not (is_staff(request.user) and request.user.is_superuser):
            raise PermissionDenied("Omborchini faqat administrator tayinlaydi.")
        uid = request.data.get("user")
        user = None
        if uid not in (None, ""):
            try:
                uid = int(uid)
            except (TypeError, ValueError):
                raise ValidationError({"user": "Noto'g'ri qiymat."})
            user = User.objects.filter(pk=uid).first()
            if not user:
                raise ValidationError({"user": "Foydalanuvchi topilmadi."})
        cfg = W.assign_keeper(user)
        return Response({"keeper": UserShortSerializer(cfg.keeper).data if cfg.keeper else None})


class WarehouseExportView(APIView):
    permission_classes = [ModelPermissions]
    queryset = Product.objects.none()

    def get(self, request):
        start, end = date_range(request.query_params)
        resp = HttpResponse(
            build_xlsx(start, end),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        resp["Content-Disposition"] = 'attachment; filename="Ombor.xlsx"'
        return resp
