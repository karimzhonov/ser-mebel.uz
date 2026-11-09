"""Bot API - Ombor: the warehouse keeper (omborchi) runs the warehouse from Telegram.

The actor is the panel user linked to the Telegram account and must be THE keeper
(`warehouse.services.is_keeper`); every other rule lives in warehouse/services.py.
Contract: docs/BOT_CONTRACT.md, "Ombor".
"""

from __future__ import annotations

from decimal import Decimal

from django.http import HttpResponse
from rest_framework import serializers
from rest_framework.exceptions import NotFound, ParseError, PermissionDenied
from rest_framework.response import Response

from core.exceptions import ServiceError
from warehouse import dto
from warehouse import services as W
from warehouse.models import UNITS, Movement, Product, ProductPhoto

from .base import BotAPIView

PAGE_SIZE = 8
MAX_CATEGORIES = 40


def _validated(serializer_class, data) -> dict:
    """Run an input serializer; a bad body becomes a 400 `{detail, field}`."""
    if not isinstance(data, dict):
        raise ParseError("So'rov noto'g'ri.")
    s = serializer_class(data=data)
    if not s.is_valid():
        field, errors = next(iter(s.errors.items()))
        code = getattr(errors[0], "code", "") if isinstance(errors, list) else ""
        msg = "To'ldirilmagan." if code in ("required", "blank", "null") else "Noto'g'ri qiymat."
        raise ServiceError(msg, field=field)
    return s.validated_data


def _page(request, qs) -> tuple[list, dict]:
    try:
        page = int(request.query_params.get("page") or 1)
    except ValueError:
        page = 1
    total = qs.count()
    pages = max(1, -(-total // PAGE_SIZE))
    page = min(max(page, 1), pages)
    items = list(qs[(page - 1) * PAGE_SIZE : page * PAGE_SIZE])
    return items, {"page": page, "pages": pages, "total": total}


def _flag(request, name: str) -> bool:
    return request.query_params.get(name) == "1"


def _product(pk) -> Product:
    p = Product.objects.prefetch_related("photos").filter(pk=pk).first()
    if p is None:
        raise NotFound("Mahsulot topilmadi")
    return p


def _product_data(pk) -> dict:
    """The product freshly read (photos included) - what write responses carry."""
    return dto.product_dto(_product(pk), with_photos=True)


def _movements():
    return Movement.objects.select_related("product", "created_by").prefetch_related("allocations")


class WarehouseBotView(BotAPIView):
    def keeper(self):
        user = self.require_linked_user()
        if not W.is_keeper(user):
            raise PermissionDenied("Ombor faqat omborchi uchun.")
        return user


class _ProductCreate(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    unit = serializers.ChoiceField(choices=[u for u, _ in UNITS])
    category = serializers.CharField(max_length=128, required=False, allow_blank=True)
    code = serializers.CharField(max_length=64, required=False, allow_blank=True)
    min_quantity = serializers.DecimalField(
        max_digits=14, decimal_places=3, required=False, min_value=Decimal("0")
    )


class _ProductPatch(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False)
    code = serializers.CharField(max_length=64, required=False, allow_blank=True)
    category = serializers.CharField(max_length=128, required=False, allow_blank=True)
    unit = serializers.ChoiceField(choices=[u for u, _ in UNITS], required=False)
    min_quantity = serializers.DecimalField(
        max_digits=14, decimal_places=3, required=False, min_value=Decimal("0")
    )
    is_active = serializers.BooleanField(required=False)


class _AllocationIn(serializers.Serializer):
    ref = serializers.CharField(max_length=32)
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3)


class _MovementIn(serializers.Serializer):
    product = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=["in", "out"])
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, required=False)
    allocations = _AllocationIn(many=True, required=False, max_length=20)
    currency = serializers.ChoiceField(choices=["UZS", "USD"], default="UZS")
    unit_price = serializers.DecimalField(max_digits=16, decimal_places=2, required=False)
    orig_price = serializers.DecimalField(max_digits=16, decimal_places=2, required=False)
    counterparty = serializers.CharField(required=False, allow_blank=True, max_length=255)
    comment = serializers.CharField(required=False, allow_blank=True)


class _ResolveIn(serializers.Serializer):
    text = serializers.CharField(max_length=500)


class _FileId(serializers.Serializer):
    file_id = serializers.CharField(max_length=255)


class MetaView(WarehouseBotView):
    """GET -> {units, categories (max 40), usd_rate, max_photos}."""

    def get(self, request):
        self.keeper()
        cats = (
            Product.objects.exclude(category="")
            .values_list("category", flat=True)
            .distinct()
            .order_by("category")[:MAX_CATEGORIES]
        )
        return Response(
            {
                "units": [{"value": v, "label": label} for v, label in UNITS],
                "categories": list(cats),
                "usd_rate": str(Decimal(W.usd_rate()).quantize(Decimal("0.0001"))),
                "max_photos": W.MAX_PHOTOS,
            }
        )


class ProductsView(WarehouseBotView):
    """GET ?q=&low=&inactive=&page= -> {items, page, pages, total}; POST -> 201 {product}."""

    def get(self, request):
        self.keeper()
        qs = W.find_products(
            request.query_params.get("q", ""),
            low=_flag(request, "low"),
            include_inactive=_flag(request, "inactive"),
        )
        items, meta = _page(request, qs)
        return Response({"items": [dto.product_dto(p) for p in items], **meta})

    def post(self, request):
        user = self.keeper()
        data = _validated(_ProductCreate, request.data)
        p = W.save_product(user, dict(data))
        return Response({"product": _product_data(p.pk)}, status=201)


class ProductView(WarehouseBotView):
    """GET -> {product, last_in, recent}; PATCH -> {product}."""

    def get(self, request, pk):
        self.keeper()
        p = _product(pk)
        last = W.last_purchase(p)
        recent = _movements().filter(product=p).order_by("-date", "-number")[:5]
        return Response(
            {
                "product": dto.product_dto(p, with_photos=True),
                "last_in": (
                    {
                        "unit_price": str(W.q2(last.unit_price)),
                        "currency": last.currency,
                        "orig_price": (
                            str(W.q2(last.orig_price)) if last.orig_price is not None else None
                        ),
                        "counterparty": last.counterparty,
                        "date": last.date.isoformat(),
                    }
                    if last
                    else None
                ),
                "recent": [dto.movement_dto(m) for m in recent],
            }
        )

    def patch(self, request, pk):
        user = self.keeper()
        p = _product(pk)
        data = _validated(_ProductPatch, request.data)
        W.save_product(user, dict(data), p)
        return Response({"product": _product_data(p.pk)})


class ProductPhotosView(WarehouseBotView):
    """POST multipart `file` (+ `tg_file_id`) -> 201 {photo, product}; 400 field "file"."""

    def post(self, request, pk):
        user = self.keeper()
        p = _product(pk)
        upload = request.FILES.get("file")
        if upload is None:
            raise ServiceError("Rasm yuborilmadi.", field="file")
        if upload.size > W.PHOTO_MAX_BYTES:
            raise ServiceError("Rasm 10 MB dan katta bo'lmasin.", field="file")
        photo = W.add_product_photo(
            user, p, upload.read(), tg_file_id=str(request.data.get("tg_file_id") or "")
        )
        return Response({"photo": dto.photo_dto(photo), "product": _product_data(p.pk)}, status=201)


class _PhotoView(WarehouseBotView):
    def get_photo(self, pk) -> ProductPhoto:
        photo = ProductPhoto.objects.filter(pk=pk).first()
        if photo is None:
            raise NotFound("Rasm topilmadi")
        return photo


class PhotoView(_PhotoView):
    """DELETE -> {product}."""

    def delete(self, request, pk):
        user = self.keeper()
        p = W.delete_product_photo(user, self.get_photo(pk))
        return Response({"product": _product_data(p.pk)})


class PhotoCoverView(_PhotoView):
    """POST -> {product}: this picture becomes the first."""

    def post(self, request, pk):
        user = self.keeper()
        p = W.set_product_cover(user, self.get_photo(pk))
        return Response({"product": _product_data(p.pk)})


class PhotoFileView(_PhotoView):
    """GET -> the main picture (image/jpeg, at most 1600 px)."""

    def get(self, request, pk):
        self.keeper()
        photo = self.get_photo(pk)
        try:
            with photo.image.open("rb") as f:
                body = f.read()
        except (FileNotFoundError, ValueError, OSError):
            raise NotFound("Rasm fayli topilmadi")
        return HttpResponse(body, content_type="image/jpeg")


class PhotoTgFileView(_PhotoView):
    """POST {file_id} -> 204: cache Telegram's file_id of the main picture."""

    def post(self, request, pk):
        self.keeper()
        photo = self.get_photo(pk)
        data = _validated(_FileId, request.data)
        W.set_photo_tg_file_id(photo, data["file_id"])
        return Response(status=204)


class MovementsView(WarehouseBotView):
    """GET ?product=&page= -> {items, page, pages, total} (newest first, cancelled
    included); POST -> 201 {movement, product}."""

    def get(self, request):
        self.keeper()
        qs = _movements().order_by("-date", "-number")
        product = request.query_params.get("product")
        if product:
            try:
                qs = qs.filter(product_id=int(product))
            except ValueError:
                raise ServiceError("Mahsulot noto'g'ri.", field="product")
        items, meta = _page(request, qs)
        return Response({"items": [dto.movement_dto(m) for m in items], **meta})

    def post(self, request):
        user = self.keeper()
        d = _validated(_MovementIn, request.data)
        p = Product.objects.filter(pk=d["product"]).first()
        if p is None:
            raise NotFound("Mahsulot topilmadi")
        m = W.add_movement(
            user,
            product=p,
            kind=d["kind"],
            quantity=d.get("quantity"),
            unit_price=d.get("unit_price"),
            currency=d["currency"],
            orig_price=d.get("orig_price"),
            counterparty=d.get("counterparty", ""),
            allocations=[dict(a) for a in d.get("allocations") or []],
            comment=d.get("comment", ""),
        )
        m = _movements().get(pk=m.pk)
        return Response(
            {"movement": dto.movement_dto(m), "product": _product_data(p.pk)}, status=201
        )


class OrdersView(WarehouseBotView):
    """GET ?q= -> {items: [WhOrderRef]} (max 24): active orders to give a chiqim to."""

    def get(self, request):
        self.keeper()
        items = W.order_choices(request.query_params.get("q", ""), 24)
        return Response({"items": [dto.order_ref_dto(o) for o in items]})


class OrdersResolveView(WarehouseBotView):
    """POST {text} -> {items: [WhOrderRef], unknown: [str]} for typed IDs («406 SM-003 999»)."""

    def post(self, request):
        self.keeper()
        data = _validated(_ResolveIn, request.data)
        res = W.resolve_refs(data["text"])
        return Response(
            {"items": [dto.order_ref_dto(o) for o in res["items"]], "unknown": res["unknown"]}
        )


class MovementCancelView(WarehouseBotView):
    """POST -> {movement, product}; 409 already cancelled; 400 stock would go negative."""

    def post(self, request, number):
        user = self.keeper()
        m = _movements().filter(number=number).first()
        if m is None:
            raise NotFound("Yozuv topilmadi")
        W.cancel_movement(user, m)
        m = _movements().get(pk=m.pk)
        return Response({"movement": dto.movement_dto(m), "product": _product_data(m.product_id)})


class SummaryView(WarehouseBotView):
    """GET ?period=today|week|month -> the stock and the period's kirim / chiqim."""

    def get(self, request):
        self.keeper()
        period = request.query_params.get("period") or "today"
        start, end = W.period_bounds(period)
        s = W.summary(start, end)
        return Response(
            {
                "period": period,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "products": s["products"],
                "stock_value": str(W.q2(s["stock_value"])),
                "usd_rate": str(Decimal(s["usd_rate"]).quantize(Decimal("0.0001"))),
                "low_count": len(s["low_stock"]),
                "period_in": str(W.q2(s["period_in"])),
                "period_out": str(W.q2(s["period_out"])),
            }
        )
