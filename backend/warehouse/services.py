"""Ombor rules — the only place stock changes.

- Only the warehouse keeper (WarehouseConfig.keeper) books kirim/chiqim and edits
  products; others with view permission (e.g. the owner) only look.
- A chiqim can't take more than is in stock.
- avg_cost is the weighted average purchase price (so'm) — the stock's value.
- Cancelling a movement recomputes the product from its history; refused if that
  would make the stock negative at any point.
"""

from __future__ import annotations

import io
import logging
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.contrib.auth.models import Group, Permission
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.db.models import Case, F, IntegerField, Max, Q, Sum, Value, When
from django.utils import timezone
from PIL import Image, ImageOps

from core.exceptions import ServiceConflict, ServiceError, ServiceNotFound
from oauth.models import User

from .models import Movement, MovementAllocation, Product, ProductPhoto, WarehouseConfig

KEEPER_GROUP = "Omborchi"
KEEPER_PERMS = [
    "view_product",
    "delete_product",
    "add_product",
    "change_product",
    "view_movement",
    "add_movement",
    "change_movement",
    "view_warehouseconfig",
]
ZERO = Decimal("0")
log = logging.getLogger(__name__)

# product photos
MAX_PHOTOS = 5
PHOTO_MAX_BYTES = 10 * 1024 * 1024
PHOTO_SIDE = 1600
THUMB_SIDE = 400
MAX_PIXELS = 25_000_000
HEIF_BRANDS = (b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1", b"heif")


def D(v) -> Decimal:
    return v if isinstance(v, Decimal) else Decimal(str(v or 0))


def q3(v) -> Decimal:
    return D(v).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def q2(v) -> Decimal:
    return D(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def usd_rate() -> Decimal:
    """The same dollar rate as Moliya (manual FIN_USD_RATE, else the Central Bank,
    else the site's USD_CURRENCY)."""
    from accounting.services import usd_rate as finance_rate

    return D(finance_rate())


# ------------------------------------------------------------------ keeper
def keeper() -> User | None:
    return WarehouseConfig.get().keeper


def is_keeper(user) -> bool:
    k = WarehouseConfig.get().keeper_id
    return bool(user and user.is_authenticated and k and user.pk == k)


def require_keeper(user):
    if not is_keeper(user):
        raise ServiceError("Omborga faqat mas'ul xodim (omborchi) kiritadi.")


def keeper_group() -> Group:
    group, _ = Group.objects.get_or_create(name=KEEPER_GROUP)
    perms = Permission.objects.filter(
        content_type__app_label="warehouse", codename__in=KEEPER_PERMS
    )
    group.permissions.set(perms)
    return group


@transaction.atomic
def assign_keeper(user: User | None) -> WarehouseConfig:
    """Make `user` the omborchi. Their access becomes exactly the warehouse: other
    groups and direct permissions are removed (the owner asked that the keeper sees
    only «Ombor»). A superuser can't be the keeper — they'd see everything anyway."""
    cfg = WarehouseConfig.objects.select_for_update().get_or_create(pk=1)[0]
    group = keeper_group()
    if cfg.keeper_id and (not user or cfg.keeper_id != user.pk):
        old = cfg.keeper
        old.groups.remove(group)
        if not old.groups.exists() and not old.user_permissions.exists() and not old.is_superuser:
            # the warehouse was all they had: no login to an empty panel
            old.is_staff = False
            old.save(update_fields=["is_staff"])
    if user:
        if user.is_superuser:
            raise ServiceError("Administratorni omborchi qilib bo'lmaydi — alohida xodim tanlang.")
        if not user.is_active:
            raise ServiceError("Bu foydalanuvchi faol emas.")
        user.groups.set([group])
        user.user_permissions.clear()
        if not user.is_staff:
            user.is_staff = True
            user.save(update_fields=["is_staff"])
    cfg.keeper = user
    cfg.save()
    return cfg


# ------------------------------------------------------------------ products
PRODUCT_FIELDS = {"name", "code", "category", "unit", "min_quantity", "is_active"}


def save_product(user, data: dict, product: Product | None = None) -> Product:
    """Create/edit a product. Never writes quantity/avg_cost: those belong to
    add_movement/recompute, and an edit form opened earlier must not put back an old
    stock figure."""
    require_keeper(user)
    unknown = set(data) - PRODUCT_FIELDS
    if unknown:
        raise ServiceError("Noto'g'ri maydon: " + ", ".join(sorted(unknown)))
    with transaction.atomic():
        p = Product.objects.select_for_update().get(pk=product.pk) if product else Product()
        for k, v in data.items():
            setattr(p, k, v.strip() if isinstance(v, str) else v)
        if not (p.name or "").strip():
            raise ServiceError("Mahsulot nomini kiriting.", field="name")
        if D(p.min_quantity) < 0:
            raise ServiceError("Minimal qoldiq manfiy bo'lmaydi.", field="min_quantity")
        if p.code and Product.objects.filter(code__iexact=p.code).exclude(pk=p.pk).exists():
            raise ServiceError("Bu kod boshqa mahsulotda bor.", field="code")
        if product:
            p.save(update_fields=list(data))
        else:
            p.save()
    return p


def delete_product(user, p: Product):
    require_keeper(user)
    if p.movements.exists():
        raise ServiceError(
            "Bu mahsulot bo'yicha harakatlar bor — o'chirish o'rniga «Faol emas» qiling."
        )
    with transaction.atomic():
        p = Product.objects.select_for_update().get(pk=p.pk)
        names = _photo_files(p.photos.all())
        p.delete()
        _delete_files_on_commit(names)


# ------------------------------------------------------------------ movements
def _next_number() -> int:
    return (Movement.objects.aggregate(m=Max("number"))["m"] or 0) + 1


MAX_ALLOCATIONS = 20


def _resolve_allocations(allocations, kind: str) -> list[tuple]:
    """[(OrderInfo, quantity, ref)] for a chiqim's client lines; [] when none given."""
    if not allocations:
        return []
    from accounting.services import order_info  # lazy: accounting imports warehouse

    if kind != "out":
        raise ServiceError("Kirimda mijoz tanlanmaydi.", field="allocations")
    if len(allocations) > MAX_ALLOCATIONS:
        raise ServiceError(
            f"Bitta chiqimda {MAX_ALLOCATIONS} tadan ortiq mijoz bo'lmaydi.", field="allocations"
        )
    out, seen = [], set()
    for a in allocations:
        ref = str((a or {}).get("ref") or "").strip().lstrip("#№").strip()
        if not ref:
            raise ServiceError("Mijoz ID si kiritilmagan.", field="allocations")
        try:
            q = q3(a.get("quantity"))
        except Exception:
            q = ZERO
        if q <= 0:
            raise ServiceError(
                f"«{ref}» uchun miqdor 0 dan katta bo'lishi kerak.", field="allocations"
            )
        info = order_info(ref)
        if info is None:
            raise ServiceError(f"«{ref}» ID topilmadi.", field="allocations")
        if info.ref in seen:
            raise ServiceError(f"«{info.ref}» ikki marta tanlangan.", field="allocations")
        seen.add(info.ref)
        out.append((info, q, info.ref))
    return out


def add_movement(
    user,
    *,
    product: Product,
    kind: str,
    quantity=None,
    unit_price=None,
    on_date: date | None = None,
    counterparty: str = "",
    allocations: list[dict] | None = None,
    comment: str = "",
    currency: str = "UZS",
    orig_price=None,
    rate=None,
) -> Movement:
    """unit_price is in so'm. For a dollar price pass currency="USD", orig_price
    (per unit, $) and optionally rate (default: the Moliya USD rate).

    A chiqim can name the clients it went to: allocations=[{"ref": "406", "quantity": "4"}]
    (Moliya refs). The stock goes down by the sum, ONE movement is written and every line
    is counted as that order's furnitura spending."""
    require_keeper(user)
    if kind not in ("in", "out"):
        raise ServiceError("Turi kirim yoki chiqim bo'lishi kerak.", field="kind")
    if currency not in ("UZS", "USD"):
        raise ServiceError("Valyuta so'm yoki $ bo'lishi kerak.", field="currency")
    if currency == "USD":
        if orig_price is None or D(orig_price) < 0:
            raise ServiceError("Dollar narxini kiriting.", field="orig_price")
        rate = D(rate) if rate is not None else usd_rate()
        if rate <= 0:
            raise ServiceError("Dollar kursi noto'g'ri.", field="rate")
        orig_price = q2(orig_price)
        unit_price = orig_price * rate
    else:
        orig_price, rate = None, None
        if unit_price is None and kind == "in":
            raise ServiceError("Narxni kiriting.", field="unit_price")
    # a chiqim in so'm without a price goes out at the product's average cost (taken
    # under the row lock below, so the figure is the current one)
    default_price = kind == "out" and currency == "UZS" and unit_price is None
    lines = _resolve_allocations(allocations, kind)
    if lines:
        qty = sum((q for _, q, _ in lines), ZERO)
        if quantity not in (None, "") and q3(quantity) != qty:
            raise ServiceError("Miqdor mijozlar bo'yicha yig'indiga teng emas.", field="quantity")
    else:
        qty = q3(quantity)
    price = ZERO if default_price else q2(unit_price)
    if qty <= 0:
        raise ServiceError("Miqdor 0 dan katta bo'lishi kerak.", field="quantity")
    if price < 0:
        raise ServiceError("Narx manfiy bo'lmaydi.", field="unit_price")
    if qty >= Decimal("1e9") or price >= Decimal("1e13") or qty * price >= Decimal("1e16"):
        raise ServiceError(
            "Miqdor yoki narx juda katta — tekshirib qayta kiriting.",
            field="unit_price" if price >= Decimal("1e13") else "quantity",
        )
    on_date = on_date or timezone.now().date()
    if on_date > timezone.now().date():
        raise ServiceError("Kelajakdagi sana bilan yozib bo'lmaydi.", field="date")
    for _ in range(5):
        try:
            with transaction.atomic():
                p = Product.objects.select_for_update().get(pk=product.pk)
                if not p.is_active:
                    raise ServiceError("Mahsulot faol emas.", field="product")
                if kind == "out" and qty > p.quantity:
                    raise ServiceError(
                        f"Omborda yetarli emas: {p.name} — bor {p.quantity.normalize()} {p.get_unit_display()}.",
                        field="quantity",
                    )
                if default_price:
                    price = q2(p.avg_cost)
                    if qty * price >= Decimal("1e16"):
                        raise ServiceError(
                            "Miqdor yoki narx juda katta — tekshirib qayta kiriting.",
                            field="quantity",
                        )
                if kind == "in":
                    new_qty = p.quantity + qty
                    p.avg_cost = (
                        q2((p.quantity * p.avg_cost + qty * price) / new_qty) if new_qty else ZERO
                    )
                    p.quantity = new_qty
                else:
                    p.quantity = p.quantity - qty
                p.save(update_fields=["quantity", "avg_cost"])
                line_totals = [q2(lq * price) for _, lq, _ in lines]
                m = Movement.objects.create(
                    number=_next_number(),
                    product=p,
                    kind=kind,
                    quantity=qty,
                    unit_price=price,
                    total=sum(line_totals, ZERO) if lines else q2(qty * price),
                    date=on_date,
                    counterparty=(counterparty or "")[:255],
                    comment=comment or "",
                    balance_after=p.quantity,
                    created_by=user,
                    currency=currency,
                    orig_price=orig_price,
                    rate=rate,
                )
                if lines:
                    MovementAllocation.objects.bulk_create(
                        [
                            MovementAllocation(
                                movement=m,
                                order_ref=info.ref,
                                order=info.order,
                                client=(info.client or "")[:255],
                                quantity=lq,
                                total=lt,
                            )
                            for (info, lq, _), lt in zip(lines, line_totals)
                        ]
                    )
                return m
        except IntegrityError:
            continue  # two keepers' tabs took the same number — retry
    raise ServiceError("Saqlab bo'lmadi, qayta urinib ko'ring.")


def recompute(p: Product) -> Product:
    """Quantity and average cost from the product's whole history (by number)."""
    qty, avg = ZERO, ZERO
    moves = list(p.movements.filter(is_cancelled=False).order_by("number"))
    for m in moves:
        if m.kind == "in":
            new_qty = qty + m.quantity
            avg = q2((qty * avg + m.quantity * m.unit_price) / new_qty) if new_qty else ZERO
            qty = new_qty
        else:
            qty -= m.quantity
            if qty < 0:
                raise ServiceError(
                    f"Bekor qilib bo'lmaydi: #{m.number} chiqim uchun {p.name} yetmay qoladi."
                )
        m.balance_after = qty
    Movement.objects.bulk_update(moves, ["balance_after"])
    p.quantity, p.avg_cost = qty, avg
    p.save(update_fields=["quantity", "avg_cost"])
    return p


def cancel_movement(user, m: Movement) -> Movement:
    require_keeper(user)
    with transaction.atomic():
        p = Product.objects.select_for_update().get(pk=m.product_id)
        m = Movement.objects.select_for_update().get(pk=m.pk)
        if m.is_cancelled:
            raise ServiceConflict("Bu yozuv allaqachon bekor qilingan.")
        m.is_cancelled, m.cancelled_at, m.cancelled_by = True, timezone.now(), user
        m.save(update_fields=["is_cancelled", "cancelled_at", "cancelled_by"])
        recompute(p)  # raises → the whole cancel rolls back
    return m


# ------------------------------------------------------------------ selectors
def find_products(q: str = "", *, low: bool = False, include_inactive: bool = False):
    """Products for a list/search: name, code or category contains `q`; an exact code
    match comes first. Photos are prefetched (cover without a query per row)."""
    qs = Product.objects.all()
    if not include_inactive:
        qs = qs.filter(is_active=True)
    if low:
        qs = qs.filter(min_quantity__gt=0, quantity__lte=F("min_quantity"))
    q = (q or "").strip()
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q) | Q(category__icontains=q))
        qs = qs.annotate(
            _exact=Case(
                When(code__iexact=q, then=Value(0)), default=Value(1), output_field=IntegerField()
            )
        ).order_by("_exact", "name", "id")
    else:
        qs = qs.order_by("name", "id")
    return qs.prefetch_related("photos")


def last_purchase(p: Product) -> Movement | None:
    """The newest kirim that is not cancelled (its price is offered again)."""
    return p.movements.filter(kind="in", is_cancelled=False).order_by("-date", "-number").first()


def order_spending(refs) -> dict[str, Decimal]:
    """so'm given out per order ref (non-cancelled chiqim lines) - one query."""
    rows = (
        MovementAllocation.objects.filter(
            order_ref__in=[str(r) for r in refs], movement__kind="out", movement__is_cancelled=False
        )
        .values("order_ref")
        .annotate(t=Sum("total"))
    )
    return {r["order_ref"]: r["t"] or ZERO for r in rows}


def order_spending_lines(ref: str) -> list[dict]:
    """The chiqim lines behind order_spending(), newest first."""
    qs = (
        MovementAllocation.objects.filter(
            order_ref=str(ref), movement__kind="out", movement__is_cancelled=False
        )
        .select_related("movement", "movement__product")
        .order_by("-movement__date", "-movement__number", "-id")
    )
    return [
        {
            "number": a.movement.number,
            "date": a.movement.date,
            "product": a.movement.product.name,
            "quantity": a.quantity,
            "unit_label": a.movement.product.get_unit_display(),
            "total": a.total,
        }
        for a in qs
    ]


def allocation_refs() -> set[str]:
    """Order refs that have at least one non-cancelled chiqim line."""
    return set(
        MovementAllocation.objects.filter(movement__kind="out", movement__is_cancelled=False)
        .values_list("order_ref", flat=True)
        .distinct()
    )


def order_choices(q: str = "", limit: int = 24) -> list[dict]:
    """Active orders to pick a chiqim's clients from: [{ref, client, bucket, status_label}]."""
    from accounting.services import open_orders, order_info

    q = (q or "").strip().lstrip("#№").strip()
    needle = q.lower()
    out = []
    for o in open_orders(["jarayonda", "yangi", "kutish", "yakun"]):
        if needle and needle not in o.ref.lower() and needle not in (o.client or "").lower():
            continue
        out.append(o)
    items = [_order_ref(o) for o in out[:limit]]
    if q and not any(i["ref"].lower() == needle for i in items):
        exact = order_info(q)  # a finished order typed by its ID is still allowed
        if exact is not None:
            items.insert(0, _order_ref(exact))
            items = items[:limit]
    return items


def _order_ref(o) -> dict:
    return {
        "ref": o.ref,
        "client": o.client or "",
        "bucket": o.bucket,
        "status_label": o.status_label,
    }


def resolve_refs(text: str) -> dict:
    """«406 410, sm-003 999» -> {"items": [order refs found], "unknown": [typed ids]}."""
    import re

    from accounting.services import order_info

    items, unknown, seen = [], [], set()
    for tok in re.split(r"[\s,;]+", text or "")[:MAX_ALLOCATIONS]:
        tok = tok.strip().lstrip("#№")
        if not tok:
            continue
        info = order_info(tok)
        if info is None:
            if tok not in unknown:
                unknown.append(tok)
        elif info.ref not in seen:
            seen.add(info.ref)
            items.append(_order_ref(info))
    return {"items": items, "unknown": unknown}


def period_bounds(period: str) -> tuple[date, date]:
    """today | week (from Monday) | month (from the 1st) -> (start, end) dates."""
    today = timezone.now().date()
    if period == "today":
        return today, today
    if period == "week":
        return today - timedelta(days=today.weekday()), today
    if period == "month":
        return today.replace(day=1), today
    raise ServiceError("Davr noto'g'ri.", field="period")


# ------------------------------------------------------------------ photos
def _photo_files(photos) -> list[str]:
    names = []
    for ph in photos:
        for f in (ph.image, ph.thumb):
            if f and f.name:
                names.append(f.name)
    return names


def _delete_files_on_commit(names: list[str]):
    def _go():
        for n in names:
            try:
                default_storage.delete(n)
            except Exception:  # a missing file must not break the request
                pass

    transaction.on_commit(_go)


def _bad_image(msg: str = "Rasm emas yoki buzilgan (JPG, PNG, WEBP)"):
    return ServiceError(msg, field="file")


def _encode(img: Image.Image, side: int, quality: int) -> bytes:
    out = img.copy()
    out.thumbnail((side, side), Image.LANCZOS)
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def _normalize_image(content: bytes) -> tuple[bytes, bytes]:
    """Validate an upload and re-encode it: (main <= 1600 px JPEG, thumb <= 400 px JPEG).
    EXIF is dropped, orientation applied, transparency flattened on white."""
    if not content:
        raise _bad_image("Fayl bo'sh.")
    if len(content) > PHOTO_MAX_BYTES:
        raise ServiceError("Rasm 10 MB dan katta bo'lmasin.", field="file")
    if content[4:8] == b"ftyp" and content[8:12] in HEIF_BRANDS:
        raise _bad_image("HEIC qabul qilinmaydi — JPG yoki PNG yuboring")
    try:
        img = Image.open(io.BytesIO(content))
        if img.format not in ("JPEG", "MPO", "PNG", "WEBP"):
            raise _bad_image()
        if img.width * img.height > MAX_PIXELS:
            raise _bad_image("Rasm juda katta (piksellar soni ko'p).")
        if img.format in ("JPEG", "MPO"):
            img.draft("RGB", (PHOTO_SIDE * 2, PHOTO_SIDE * 2))  # decode at a reduced size
        img.load()
        img.thumbnail((PHOTO_SIDE, PHOTO_SIDE), Image.LANCZOS)  # shrink before any copy
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            rgba = img.convert("RGBA")
            flat = Image.new("RGB", rgba.size, (255, 255, 255))
            flat.paste(rgba, mask=rgba.getchannel("A"))
            img = flat
        else:
            img = img.convert("RGB")
        main = _encode(img, PHOTO_SIDE, 85)
        thumb = _encode(Image.open(io.BytesIO(main)), THUMB_SIDE, 80)
    except ServiceError:
        raise
    except Exception:  # broken EXIF raises struct.error / KeyError / TypeError ...
        log.warning("warehouse: unreadable upload", exc_info=True)
        raise _bad_image() from None
    return main, thumb


def _renumber(photos: list[ProductPhoto]):
    for i, ph in enumerate(photos):
        ph.position = i
    ProductPhoto.objects.bulk_update(photos, ["position"])


def add_product_photo(user, product: Product, content: bytes, *, tg_file_id: str = ""):
    """Attach a picture (<= 5 per product); the new one goes last. Keeper only."""
    require_keeper(user)
    main, thumb = _normalize_image(content)  # heavy work before the row lock
    photo = None
    try:
        with transaction.atomic():
            p = Product.objects.select_for_update().get(pk=product.pk)
            n = p.photos.count()
            if n >= MAX_PHOTOS:
                raise ServiceError(
                    f"Bitta mahsulotga {MAX_PHOTOS} tadan ortiq rasm bo'lmaydi.", field="file"
                )
            photo = ProductPhoto(
                product=p,
                position=(p.photos.aggregate(m=Max("position"))["m"] + 1) if n else 0,
                tg_file_id=(tg_file_id or "")[:255],
                uploaded_by=user,
            )
            photo.image.save("photo.jpg", ContentFile(main), save=False)
            photo.thumb.save("thumb.jpg", ContentFile(thumb), save=False)
            photo.width, photo.height = Image.open(io.BytesIO(main)).size
            photo.save()
    except Exception:
        # anything failing after the files were written (incl. the commit) leaves no orphans
        if photo is not None:
            for f in (photo.image, photo.thumb):
                if f and f.name:
                    try:
                        f.storage.delete(f.name)
                    except Exception:
                        pass
        raise
    return photo


def delete_product_photo(user, photo: ProductPhoto) -> Product:
    require_keeper(user)
    with transaction.atomic():
        p = Product.objects.select_for_update().get(pk=photo.product_id)
        ph = ProductPhoto.objects.filter(pk=photo.pk).first()
        if ph is None:
            raise ServiceNotFound("Rasm topilmadi.")
        names = _photo_files([ph])
        ph.delete()
        _renumber(list(p.photos.all()))
        _delete_files_on_commit(names)
    return p


def set_product_cover(user, photo: ProductPhoto) -> Product:
    require_keeper(user)
    with transaction.atomic():
        p = Product.objects.select_for_update().get(pk=photo.product_id)
        photos = list(p.photos.all())
        target = next((x for x in photos if x.pk == photo.pk), None)
        if target is None:
            raise ServiceNotFound("Rasm topilmadi.")
        photos.remove(target)
        _renumber([target, *photos])
    return p


def set_photo_tg_file_id(photo: ProductPhoto, file_id: str):
    """Remember Telegram's file_id for the main picture (a cache only)."""
    ProductPhoto.objects.filter(pk=photo.pk).update(tg_file_id=(file_id or "")[:255])


# ------------------------------------------------------------------ reports
def summary(start: date | None = None, end: date | None = None) -> dict:
    products = Product.objects.filter(is_active=True)
    value = sum((p.quantity * p.avg_cost for p in products), ZERO)
    low = [p for p in products if p.min_quantity and p.quantity <= p.min_quantity]
    mv = Movement.objects.filter(is_cancelled=False)
    if start:
        mv = mv.filter(date__gte=start)
    if end:
        mv = mv.filter(date__lte=end)
    agg = mv.aggregate(
        inc=Sum("total", filter=Q(kind="in")),
        out=Sum("total", filter=Q(kind="out")),
    )
    return {
        "products": products.count(),
        "stock_value": q2(value),
        "low_stock": [
            {
                "id": p.id,
                "name": p.name,
                "quantity": p.quantity,
                "min_quantity": p.min_quantity,
                "unit": p.unit,
            }
            for p in low
        ],
        "usd_rate": usd_rate(),
        "period_in": q2(agg["inc"] or 0),
        "period_out": q2(agg["out"] or 0),
        "keeper": keeper(),
    }
