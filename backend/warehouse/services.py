"""Ombor rules — the only place stock changes.

- Only the warehouse keeper (WarehouseConfig.keeper) books kirim/chiqim and edits
  products; others with view permission (e.g. the owner) only look.
- A chiqim can't take more than is in stock.
- avg_cost is the weighted average purchase price (so'm) — the stock's value.
- Cancelling a movement recomputes the product from its history; refused if that
  would make the stock negative at any point.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.contrib.auth.models import Group, Permission
from django.db import IntegrityError, transaction
from django.db.models import Max, Q, Sum
from django.utils import timezone

from core.exceptions import ServiceError
from oauth.models import User
from order.models import Order

from .models import Movement, Product, WarehouseConfig

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


def D(v) -> Decimal:
    return v if isinstance(v, Decimal) else Decimal(str(v or 0))


def q3(v) -> Decimal:
    return D(v).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def q2(v) -> Decimal:
    return D(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


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
            raise ServiceError("Mahsulot nomini kiriting.")
        if D(p.min_quantity) < 0:
            raise ServiceError("Minimal qoldiq manfiy bo'lmaydi.")
        if p.code and Product.objects.filter(code__iexact=p.code).exclude(pk=p.pk).exists():
            raise ServiceError("Bu kod boshqa mahsulotda bor.")
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
    p.delete()


# ------------------------------------------------------------------ movements
def _next_number() -> int:
    return (Movement.objects.aggregate(m=Max("number"))["m"] or 0) + 1


def add_movement(
    user,
    *,
    product: Product,
    kind: str,
    quantity,
    unit_price,
    on_date: date | None = None,
    counterparty: str = "",
    order_number: int | None = None,
    comment: str = "",
) -> Movement:
    require_keeper(user)
    if kind not in ("in", "out"):
        raise ServiceError("Turi kirim yoki chiqim bo'lishi kerak.")
    qty, price = q3(quantity), q2(unit_price)
    if qty <= 0:
        raise ServiceError("Miqdor 0 dan katta bo'lishi kerak.")
    if price < 0:
        raise ServiceError("Narx manfiy bo'lmaydi.")
    if qty >= Decimal("1e9") or price >= Decimal("1e13") or qty * price >= Decimal("1e16"):
        raise ServiceError("Miqdor yoki narx juda katta — tekshirib qayta kiriting.")
    on_date = on_date or timezone.now().date()
    if on_date > timezone.now().date():
        raise ServiceError("Kelajakdagi sana bilan yozib bo'lmaydi.")
    order = None
    if order_number:
        order = Order.objects.filter(order_number=order_number).first()
        if not order:
            raise ServiceError(f"№{order_number} buyurtma topilmadi.")
    for _ in range(5):
        try:
            with transaction.atomic():
                p = Product.objects.select_for_update().get(pk=product.pk)
                if not p.is_active:
                    raise ServiceError("Mahsulot faol emas.")
                if kind == "out" and qty > p.quantity:
                    raise ServiceError(
                        f"Omborda yetarli emas: {p.name} — bor {p.quantity.normalize()} {p.get_unit_display()}."
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
                return Movement.objects.create(
                    number=_next_number(),
                    product=p,
                    kind=kind,
                    quantity=qty,
                    unit_price=price,
                    total=q2(qty * price),
                    date=on_date,
                    counterparty=(counterparty or "")[:255],
                    order=order,
                    comment=comment or "",
                    balance_after=p.quantity,
                    created_by=user,
                )
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
            raise ServiceError("Bu yozuv allaqachon bekor qilingan.")
        m.is_cancelled, m.cancelled_at, m.cancelled_by = True, timezone.now(), user
        m.save(update_fields=["is_cancelled", "cancelled_at", "cancelled_by"])
        recompute(p)  # raises → the whole cancel rolls back
    return m


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
        "period_in": q2(agg["inc"] or 0),
        "period_out": q2(agg["out"] or 0),
        "keeper": keeper(),
    }
