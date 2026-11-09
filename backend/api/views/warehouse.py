"""Ombor API. Reads need the warehouse.view_* permission; every write goes through
warehouse/services.py, which also requires the caller to be THE keeper (omborchi)."""

from __future__ import annotations

from decimal import Decimal

from django.http import HttpResponse
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from oauth.models import User
from warehouse import services as W
from warehouse.excel import build_xlsx
from warehouse.models import UNITS, Movement, Product, ProductPhoto, WarehouseConfig

from ..permissions import ModelPermissions, is_staff, require_perm
from ..serializers.common import UserShortSerializer
from ..utils import date_range, int_param


class ProductSerializer(serializers.ModelSerializer):
    unit_label = serializers.CharField(source="get_unit_display", read_only=True)
    value = serializers.SerializerMethodField()
    avg_cost_usd = serializers.SerializerMethodField()
    value_usd = serializers.SerializerMethodField()
    low = serializers.SerializerMethodField()
    photos = serializers.SerializerMethodField()
    cover = serializers.SerializerMethodField()

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
            "avg_cost_usd",
            "value_usd",
            "low",
            "is_active",
            "photos",
            "cover",
            "created_at",
        ]
        read_only_fields = ["quantity", "avg_cost", "created_at"]

    @staticmethod
    def _photo(ph):
        return {
            "id": ph.pk,
            "url": ph.image.url,
            "thumb": ph.thumb.url if ph.thumb else ph.image.url,
            "position": ph.position,
            "width": ph.width,
            "height": ph.height,
        }

    def get_photos(self, obj):
        return [self._photo(ph) for ph in obj.photos.all()]

    def get_cover(self, obj):
        photos = obj.photos.all()
        return self._photo(photos[0]) if photos else None

    def get_value(self, obj):
        return round(float(obj.quantity * obj.avg_cost), 2)

    def _rate(self):
        # one rate per response (it is cached, but the list has many rows)
        if "usd_rate" not in self.context:
            self.context["usd_rate"] = W.usd_rate()
        return self.context["usd_rate"]

    def get_avg_cost_usd(self, obj):
        r = self._rate()
        return round(float(obj.avg_cost / r), 2) if r else None

    def get_value_usd(self, obj):
        r = self._rate()
        return round(float(obj.quantity * obj.avg_cost / r), 2) if r else None

    def get_low(self, obj):
        return bool(obj.min_quantity) and obj.quantity <= obj.min_quantity


class MovementSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    product_unit = serializers.CharField(source="product.get_unit_display", read_only=True)
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    allocations = serializers.SerializerMethodField()
    created_by_detail = UserShortSerializer(source="created_by", read_only=True)

    def get_allocations(self, obj):
        return [
            {
                "ref": a.order_ref,
                "client": a.client,
                "quantity": a.quantity,
                "total": a.total,
                "order_id": a.order_id,
            }
            for a in obj.allocations.all()
        ]

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
            "currency",
            "orig_price",
            "rate",
            "unit_price",
            "total",
            "date",
            "counterparty",
            "allocations",
            "comment",
            "balance_after",
            "created_by_detail",
            "created_at",
            "is_cancelled",
            "cancelled_at",
        ]
        read_only_fields = fields


class AllocationInputSerializer(serializers.Serializer):
    ref = serializers.CharField(max_length=32)
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3)


class MovementInputSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    kind = serializers.ChoiceField(choices=["in", "out"])
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, required=False)
    allocations = AllocationInputSerializer(many=True, required=False, max_length=20)
    currency = serializers.ChoiceField(choices=["UZS", "USD"], default="UZS")
    unit_price = serializers.DecimalField(max_digits=16, decimal_places=2, required=False)
    orig_price = serializers.DecimalField(max_digits=16, decimal_places=2, required=False)
    rate = serializers.DecimalField(
        max_digits=16, decimal_places=4, required=False, min_value=Decimal("0.0001")
    )

    def validate(self, attrs):
        if attrs.get("quantity") is None and not attrs.get("allocations"):
            raise serializers.ValidationError({"quantity": "Miqdorni kiriting."})
        if attrs.get("currency") == "USD" and attrs.get("orig_price") is None:
            raise serializers.ValidationError({"orig_price": "Dollar narxini kiriting."})
        if attrs.get("currency", "UZS") == "UZS" and attrs.get("unit_price") is None:
            raise serializers.ValidationError({"unit_price": "Narxni kiriting."})
        return attrs

    date = serializers.DateField(required=False)
    counterparty = serializers.CharField(required=False, allow_blank=True, max_length=255)
    comment = serializers.CharField(required=False, allow_blank=True)


class ProductViewSet(viewsets.ModelViewSet):
    permission_classes = [ModelPermissions]
    serializer_class = ProductSerializer
    search_fields = ["name", "code", "category"]
    ordering_fields = ["name", "quantity", "category"]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = Product.objects.prefetch_related("photos")
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

    def _photo_or_404(self, product, photo_id) -> ProductPhoto:
        photo = product.photos.filter(pk=photo_id).first()
        if photo is None:
            raise NotFound("Rasm topilmadi.")
        return photo

    def _fresh(self, product):
        # re-read with the photos so the answer shows the new order
        return ProductSerializer(Product.objects.prefetch_related("photos").get(pk=product.pk)).data

    @action(
        detail=True,
        methods=["post"],
        url_path="photos",
        parser_classes=[MultiPartParser, FormParser],
    )
    def photos(self, request, pk=None):
        require_perm(request.user, "warehouse.change_product")
        product = self.get_object()
        up = request.FILES.get("file")
        if up is None:
            raise ValidationError({"file": "Rasm faylini yuboring."})
        if up.size > W.PHOTO_MAX_BYTES:
            raise ValidationError({"file": "Rasm 10 MB dan katta bo'lmasin."})
        W.add_product_photo(request.user, product, up.read())
        return Response(self._fresh(product), status=201)

    @action(detail=True, methods=["delete"], url_path=r"photos/(?P<photo_id>\d+)")
    def photo(self, request, pk=None, photo_id=None):
        require_perm(request.user, "warehouse.change_product")
        product = self.get_object()
        W.delete_product_photo(request.user, self._photo_or_404(product, photo_id))
        return Response(self._fresh(product))

    @action(detail=True, methods=["post"], url_path=r"photos/(?P<photo_id>\d+)/cover")
    def photo_cover(self, request, pk=None, photo_id=None):
        require_perm(request.user, "warehouse.change_product")
        product = self.get_object()
        W.set_product_cover(request.user, self._photo_or_404(product, photo_id))
        return Response(self._fresh(product))

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
    search_fields = [
        "product__name",
        "counterparty",
        "comment",
        "allocations__order_ref",
        "allocations__client",
    ]
    ordering_fields = ["number", "date"]

    def get_queryset(self):
        qs = Movement.objects.select_related("product", "created_by").prefetch_related(
            "allocations"
        )
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
        if p.get("order"):
            qs = qs.filter(
                allocations__order_ref__iexact=p["order"].strip().lstrip("#№")
            ).distinct()
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
            quantity=d.get("quantity"),
            unit_price=d.get("unit_price"),
            currency=d.get("currency", "UZS"),
            orig_price=d.get("orig_price"),
            rate=d.get("rate"),
            on_date=d.get("date"),
            counterparty=d.get("counterparty", ""),
            allocations=[dict(a) for a in d.get("allocations") or []],
            comment=d.get("comment", ""),
        )
        return Response(MovementSerializer(m).data, status=201)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        m = W.cancel_movement(request.user, self.get_object())
        return Response(MovementSerializer(m).data)


class WarehouseOrderOptionsView(APIView):
    """GET ?search= -> active orders / client IDs to give a chiqim to."""

    permission_classes = [ModelPermissions]
    queryset = Movement.objects.none()

    def get(self, request):
        return Response(W.order_choices(request.query_params.get("search", ""), 30))


class WarehouseSummaryView(APIView):
    permission_classes = [ModelPermissions]
    queryset = Product.objects.none()

    def get(self, request):
        start, end = date_range(request.query_params)
        sm = W.summary(start, end)
        k = sm.pop("keeper")
        sm["keeper"] = UserShortSerializer(k).data if k else None
        sm["is_keeper"] = W.is_keeper(request.user)
        r = sm["usd_rate"]
        sm["stock_value_usd"] = round(float(sm["stock_value"] / r), 2) if r else None
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
