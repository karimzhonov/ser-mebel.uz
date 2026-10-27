"""Finance (Moliya) business rules — the single source of truth.

Both the Telegram bot (through the internal API api/views/bot/finance.py) and the site
REST API (api/views/finance.py) call these functions, so an operation booked in
Telegram and one booked on the site follow the same rules. Ported from code.txt
(Google Apps Script); the functions name their original in the docstring where it
helps to compare.

Telegram side effects (channel posts, "money was given to you") are not sent from
here: callers pass the returned objects to accounting/events.py, which queues events
for the bot service (core/bot_notify.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

import requests
from constance import config
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.db.models import Max, Q, Sum

from core.exceptions import ServiceConflict, ServiceError, ServiceForbidden
from oauth.models import TelegramMember, TelegramRole, User
from order.constants import OrderStatus
from order.models import Order

from .constants import (
    ARCHIVE_DAYS,
    BONUS_TIERS,
    CAT_ADVANCE,
    CAT_FROM_BOSS,
    CAT_REST,
    CAT_SALARY,
    CAT_TRANSFER,
    CategoryKind,
    OpKind,
)
from .models import (
    ClientFeedback,
    FinanceCategory,
    FinanceJobRun,
    ManualOrder,
    MoneyRequest,
    MonthReport,
    Operation,
    OrderBonus,
    SiteEntryTask,
    WarrantyLetter,
)
from .text import (
    add_months,
    cur_name,
    days_between,
    ddmm,
    fmt_cur,
    money,
    month_bounds,
    month_full,
    month_name,
    now,
    num,
    parse_money,
    today,
)

ZERO = Decimal("0")


def D(v) -> Decimal:
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v or 0))


def q2(v) -> Decimal:
    return D(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def once(key: str) -> bool:
    """True the first time `key` is seen (reminders, daily jobs) — never twice."""
    try:
        with transaction.atomic():
            FinanceJobRun.objects.create(key=key[:191])
        return True
    except IntegrityError:
        return False


# =================================================================== members
def member_by_tg(telegram_id) -> TelegramMember | None:
    try:
        return TelegramMember.objects.select_related("user").get(telegram_id=int(telegram_id))
    except (TelegramMember.DoesNotExist, TypeError, ValueError):
        return None


def admins():
    return list(TelegramMember.objects.filter(role=TelegramRole.ADMIN))


def wallets():
    """Members who have a wallet (wallets_): admins and staff, minus task-only."""
    return [
        m
        for m in TelegramMember.objects.filter(
            role__in=[TelegramRole.ADMIN, TelegramRole.STAFF]
        ).select_related("user")
        if m.has_wallet
    ]


def staff():
    return [m for m in wallets() if m.role == TelegramRole.STAFF]


def duty_members(duty: str):
    """duty: is_site_entry / is_feedback / is_bonus_receiver / is_deadline_receiver."""
    return list(
        TelegramMember.objects.filter(
            **{duty: True}, role__in=[TelegramRole.ADMIN, TelegramRole.STAFF]
        )
    )


def register_member(telegram_id: int, name: str, username: str = "") -> tuple[TelegramMember, bool]:
    """Unknown account asks to join → pending, waiting for an admin.

    Never linked to a site account automatically: an admin links them on the site
    (Moliya → Sozlamalar)."""
    m = member_by_tg(telegram_id)
    if m:
        return m, False
    m = TelegramMember.objects.create(
        telegram_id=telegram_id,
        name=(name or username or str(telegram_id))[:255],
        username=(username or "")[:255],
        role=TelegramRole.PENDING,
    )
    return m, True


def set_member_role(member: TelegramMember, role: str) -> TelegramMember:
    if role not in TelegramRole.values:
        raise ServiceError("Noto'g'ri rol.")
    member.role = role
    member.save(update_fields=["role", "updated_at"])
    return member


def set_duty_exclusive(member: TelegramMember, duty: str) -> None:
    """/saytchi and /fikrchi pick ONE person for the duty (setCfg_ overwrote the id)."""
    if duty not in ("is_site_entry", "is_feedback"):
        raise ServiceError("Noto'g'ri vazifa.")
    with transaction.atomic():
        TelegramMember.objects.filter(**{duty: True}).exclude(pk=member.pk).update(**{duty: False})
        setattr(member, duty, True)
        member.save(update_fields=[duty, "updated_at"])


# =================================================================== categories
def categories(kind: str | None = None, active=True):
    qs = FinanceCategory.objects.all()
    if active:
        qs = qs.filter(is_active=True)
    if kind:
        qs = qs.filter(kind=kind)
    return list(qs)


def category(code: str) -> FinanceCategory | None:
    return FinanceCategory.objects.filter(code=code).first()


# =================================================================== USD rate
def usd_rate() -> Decimal:
    """FIN_USD_RATE if set, else the Central Bank rate (3h cache), else the site's
    USD_CURRENCY setting."""
    manual = D(config.FIN_USD_RATE)
    if manual > 0:
        return manual
    cached = cache.get("fin_cbu_usd")
    if cached:
        return D(cached)
    if not cache.get("fin_cbu_down"):
        try:
            r = requests.get("https://cbu.uz/uz/arkhiv-kursov-valyut/json/USD/", timeout=4)
            rate = D(r.json()[0]["Rate"])
            if rate > 0:
                cache.set("fin_cbu_usd", str(rate), 3 * 3600)
                return rate
        except Exception:  # noqa: BLE001 — network/JSON: fall back to the site rate
            pass
        # remember the failure: one slow lookup, not one per order in a list
        cache.set("fin_cbu_down", "1", 10 * 60)
    return D(config.USD_CURRENCY)


def money_in(text: str) -> dict:
    """«500000», «1.5 mln», «300$» → {amount (so'm), cur, orig, rate} (reqMoneyIn_)."""
    val, cur = parse_money(text)
    if not val:
        raise ServiceError("Summani tushunmadim. Masalan: 500000, 1.5 mln yoki 300$")
    if cur != "USD":
        return {"amount": q2(round(val)), "cur": "UZS", "orig": None, "rate": None}
    rate = usd_rate()
    if not rate:
        raise ServiceError(
            "Dollar kursi topilmadi — so'mda yozing yoki rahbar /kurs 12050 qilib kursni kiritsin."
        )
    return {"amount": q2(round(val * rate)), "cur": "USD", "orig": val, "rate": rate}


def money_text(m: dict) -> str:
    """«300 USD (≈ 3 540 000 so'm)» or «500 000 so'm» (reqMoney_)."""
    if m.get("cur") == "USD":
        return f"{num(m.get('orig'))} USD (≈ {money(m['amount'])})"
    return money(m["amount"])


# =================================================================== orders
@dataclass
class OrderInfo:
    ref: str
    client: str = ""
    phone: str = ""
    order: Order | None = None
    manual: ManualOrder | None = None
    bucket: str = "jarayonda"  # yangi | jarayonda | kutish | yakun | tugadi
    status_label: str = ""
    total: Decimal = ZERO  # in `currency`
    currency: str = "UZS"
    paid: Decimal | None = None
    rest: Decimal | None = None
    price_uzs: Decimal = ZERO  # contract in so'm (for profit/debt maths)
    end_date: date | None = None
    ready_date: date | None = None
    address: str = ""
    furniture: str = ""
    extra: dict = field(default_factory=dict)


def _done_dates(order_ids) -> dict[int, date]:
    """When each order last became «Готов», from the order history."""
    if not order_ids:
        return {}
    History = Order.history.model
    rows = (
        History.objects.filter(id__in=list(order_ids))
        .order_by("id", "history_date")
        .values_list("id", "status", "history_date")
    )
    out: dict[int, date] = {}
    prev: dict[int, str] = {}
    for oid, status, hdate in rows:
        if status == OrderStatus.DONE and prev.get(oid) != OrderStatus.DONE:
            out[oid] = hdate.date() if isinstance(hdate, datetime) else hdate
        prev[oid] = status
    return out


def _bucket(order: Order, ready: date | None) -> str:
    if order.status == OrderStatus.DONE:
        if ready and days_between(ready, today()) <= int(config.FIN_READY_DAYS or 30):
            return "yakun"
        return "tugadi"
    if order.status == OrderStatus.DETAILING:
        return "yangi"
    if order.status == OrderStatus.WAITING:
        return "kutish"
    return "jarayonda"


def _order_money(order: Order) -> tuple[Decimal, str, Decimal | None]:
    if not order.price:
        return ZERO, "UZS", None
    cur = str(order.price.currency)
    total = q2(D(order.price.amount) * (1 - D(order.discount or 0) / 100))
    paid = None
    if order.lost_money is not None:
        paid = D(order.lost_money.amount)
        if str(order.lost_money.currency) != cur:
            rate = usd_rate()
            paid = paid * rate if cur == "UZS" else (paid / rate if rate else ZERO)
        paid = q2(paid)
    return total, cur, paid


def _info_from_order(order: Order, ready: date | None) -> OrderInfo:
    total, cur, paid = _order_money(order)
    rest = None if paid is None or not total else max(ZERO, total - paid)
    client = order.client
    furniture = ""
    if getattr(order, "design_type", None):
        furniture = str(order.design_type)
    elif order.desc:
        furniture = order.desc.strip().splitlines()[0][:60]
    return OrderInfo(
        ref=str(order.order_number),
        client=(client.fio if client else "") or f"Mijoz #{order.order_number}",
        phone=str(client.phone) if client and client.phone else "",
        order=order,
        bucket=_bucket(order, ready),
        status_label=order.get_status_display(),
        total=total,
        currency=cur,
        paid=paid,
        rest=rest,
        price_uzs=q2(total * usd_rate()) if cur == "USD" else total,
        end_date=order.end_date,
        ready_date=ready,
        address=order.address or "",
        furniture=furniture,
    )


def _site_orders_qs():
    return Order.objects.select_related("client", "design_type").exclude(order_number__isnull=True)


def order_info(ref: str | None) -> OrderInfo | None:
    ref = str(ref or "").strip().lstrip("#")
    if not ref:
        return None
    if ref.isdigit():
        order = _site_orders_qs().filter(order_number=int(ref)).first()
        if order:
            ready = None
            if order.status == OrderStatus.DONE:
                ready = _done_dates([order.id]).get(order.id)
                bonus = OrderBonus.objects.filter(order_ref=ref).first()
                if bonus:
                    ready = bonus.ready_date
            return _info_from_order(order, ready)
    mo = ManualOrder.objects.filter(ref__iexact=ref).first()
    if mo:
        return OrderInfo(
            ref=mo.ref,
            client=mo.client,
            phone=mo.phone,
            manual=mo,
            bucket="tugadi" if mo.is_closed else "jarayonda",
            status_label="Yopilgan" if mo.is_closed else "Jarayonda",
            total=mo.price,
            price_uzs=mo.price,
            ready_date=mo.closed,
        )
    return None


def open_orders(buckets: list[str]) -> list[OrderInfo]:
    """Site orders (+ open manual orders) in the given buckets, order of `buckets`."""
    qs = _site_orders_qs()
    want_done = "yakun" in buckets or "tugadi" in buckets
    statuses = []
    if "jarayonda" in buckets:
        statuses += [
            OrderStatus.CREATED,
            OrderStatus.WORKING,
            OrderStatus.ASSEMBLY,
            OrderStatus.INSTALLING,
        ]
    if "yangi" in buckets:
        statuses.append(OrderStatus.DETAILING)
    if "kutish" in buckets:
        statuses.append(OrderStatus.WAITING)
    if want_done:
        statuses.append(OrderStatus.DONE)
    orders = list(qs.filter(status__in=statuses).order_by("-order_number"))
    done_ids = [o.id for o in orders if o.status == OrderStatus.DONE]
    ready = _done_dates(done_ids)
    bonus_ready = dict(
        OrderBonus.objects.filter(order_ref__in=[str(o.order_number) for o in orders]).values_list(
            "order_ref", "ready_date"
        )
    )
    out = []
    for o in orders:
        r = bonus_ready.get(str(o.order_number)) or ready.get(o.id)
        info = _info_from_order(o, r)
        if info.bucket in buckets:
            out.append(info)
    if "jarayonda" in buckets:
        for mo in ManualOrder.objects.filter(is_closed=False):
            out.append(
                OrderInfo(
                    ref=mo.ref,
                    client=mo.client,
                    phone=mo.phone,
                    manual=mo,
                    total=mo.price,
                    price_uzs=mo.price,
                )
            )
    order_pos = {b: i for i, b in enumerate(buckets)}
    out.sort(key=lambda x: order_pos.get(x.bucket, 99))
    return out


def archive_orders() -> list[OrderInfo]:
    """«🗄 Arxiv ID»: Готов within the last ARCHIVE_DAYS days, newest first."""
    orders = list(_site_orders_qs().filter(status=OrderStatus.DONE))
    ready = _done_dates([o.id for o in orders])
    since = today() - timedelta(days=ARCHIVE_DAYS)
    out = []
    for o in orders:
        r = ready.get(o.id) or o.end_date
        if r and r >= since:
            out.append(_info_from_order(o, r))
    out.sort(key=lambda x: (x.ready_date or date.min, int(x.ref)), reverse=True)
    return out


def all_order_ids() -> list[str]:
    ids = [
        str(n)
        for n in Order.objects.exclude(order_number__isnull=True).values_list(
            "order_number", flat=True
        )
    ]
    return ids + list(ManualOrder.objects.values_list("ref", flat=True))


def order_stats(ref: str) -> dict:
    """Spent / collected per order (orderStats_)."""
    rows = list(
        Operation.objects.filter(order_ref=str(ref), is_deleted=False)
        .select_related("category", "member")
        .order_by("date", "number")
    )
    st = {"spent": ZERO, "collected": ZERO, "cats": {}, "rows": rows}
    for t in rows:
        if t.kind == OpKind.EXPENSE:
            st["spent"] += t.amount
            st["cats"][t.category.code] = st["cats"].get(t.category.code, ZERO) + t.amount
        elif t.category.code in (CAT_ADVANCE, CAT_REST):
            st["collected"] += t.amount
    return st


def order_stats_bulk(refs) -> dict[str, dict]:
    """spent / collected / per-category for many orders in one query."""
    out: dict[str, dict] = {}
    rows = (
        Operation.objects.filter(order_ref__in=list(refs), is_deleted=False)
        .values("order_ref", "kind", "category__code")
        .annotate(total=Sum("amount"))
    )
    for r in rows:
        st = out.setdefault(r["order_ref"], {"spent": ZERO, "collected": ZERO, "cats": {}})
        if r["kind"] == OpKind.EXPENSE:
            st["spent"] += r["total"]
            st["cats"][r["category__code"]] = st["cats"].get(r["category__code"], ZERO) + r["total"]
        elif r["category__code"] in (CAT_ADVANCE, CAT_REST):
            st["collected"] += r["total"]
    return out


def order_infos(refs) -> dict[str, OrderInfo]:
    """order_info() for many refs with a fixed number of queries."""
    refs = [str(r) for r in refs if r]
    nums = [int(r) for r in refs if r.isdigit()]
    orders = list(_site_orders_qs().filter(order_number__in=nums))
    done = _done_dates([o.id for o in orders if o.status == OrderStatus.DONE])
    bonus_ready = dict(
        OrderBonus.objects.filter(order_ref__in=refs).values_list("order_ref", "ready_date")
    )
    out = {}
    for o in orders:
        ref = str(o.order_number)
        out[ref] = _info_from_order(o, bonus_ready.get(ref) or done.get(o.id))
    rest = [r for r in refs if r not in out]
    for mo in ManualOrder.objects.filter(ref__in=rest):
        out[mo.ref] = OrderInfo(
            ref=mo.ref,
            client=mo.client,
            phone=mo.phone,
            manual=mo,
            bucket="tugadi" if mo.is_closed else "jarayonda",
            status_label="Yopilgan" if mo.is_closed else "Jarayonda",
            total=mo.price,
            price_uzs=mo.price,
            ready_date=mo.closed,
        )
    return out


def create_manual_order(ref: str, client: str, phone: str = "", price=0) -> ManualOrder:
    ref = str(ref).strip()
    if not ref:
        raise ServiceError("ID kiritilmagan.")
    if not re.fullmatch(r"[A-Za-z0-9-]{1,20}", ref):
        raise ServiceError(
            "ID faqat lotin harflari, raqamlar va «-» dan iborat bo'lishi kerak (20 tagacha)."
        )
    if order_info(ref):
        raise ServiceError("Bu ID band. Boshqasini yozing.")
    return ManualOrder.objects.create(
        ref=ref, client=client[:255], phone=phone[:64], price=q2(price), opened=today()
    )


def next_manual_ref() -> str:
    nums = []
    for ref in ManualOrder.objects.values_list("ref", flat=True):
        if ref.upper().startswith("SM-") and ref[3:].isdigit():
            nums.append(int(ref[3:]))
    return f"SM-{(max(nums) if nums else 0) + 1:03d}"


def _resolve_order(ref: str | None) -> tuple[str, Order | None]:
    ref = str(ref or "").strip().lstrip("#")[:32]
    if not ref:
        return "", None
    order = Order.objects.filter(order_number=int(ref)).first() if ref.isdigit() else None
    return ref, order


# =================================================================== operations
def _next_number(model) -> int:
    return (model.objects.aggregate(m=Max("number"))["m"] or 0) + 1


def create_operation(
    *,
    member: TelegramMember,
    kind: str,
    amount,
    category_code: str,
    author: TelegramMember | None = None,
    currency: str = "UZS",
    orig_amount=None,
    rate=None,
    order_ref: str | None = None,
    comment: str = "",
    receipt_file_id: str = "",
    worker: str = "",
    pay_type: str = "",
    source: str = "bot",
    site_user: User | None = None,
    on_date: date | None = None,
    at_time: time | None = None,
    number: int | None = None,
    actor_admin: bool = False,
    internal: bool = False,
) -> Operation:
    """addTx_: one row in a member's wallet.

    actor_admin: the person booking is a finance admin (rahbar / site user with
    view_all_operations). internal=True is for rows this module books itself
    (transfers, «Rahbardan», «Pul oldim») — the caller already checked who may."""
    if kind not in OpKind.values:
        raise ServiceError("Noto'g'ri tur.")
    amount = q2(amount)
    if amount <= 0:
        raise ServiceError("Summa 0 dan katta bo'lishi kerak.")
    cat = category(category_code)
    if not cat:
        raise ServiceError("Kategoriya topilmadi.")
    if cat.kind == CategoryKind.EXPENSE and kind != OpKind.EXPENSE:
        raise ServiceError("Bu kategoriya faqat chiqim uchun.")
    if cat.kind == CategoryKind.INCOME and kind != OpKind.INCOME:
        raise ServiceError("Bu kategoriya faqat kirim uchun.")
    if currency == "USD" and (not orig_amount or not rate):
        raise ServiceError("Dollar summasi va kursi kerak.")
    if not internal:
        _check_category_allowed(cat, actor_admin)
        _check_date_allowed(on_date, actor_admin)
    ref, order = _resolve_order(order_ref)
    if kind == OpKind.EXPENSE and (cat.no_order or cat.code == CAT_SALARY):
        ref, order = "", None
    stamp = now()
    for _ in range(5):
        try:
            with transaction.atomic():
                return Operation.objects.create(
                    number=number or _next_number(Operation),
                    date=on_date or stamp.date(),
                    time=(
                        at_time
                        if (at_time or on_date)
                        else stamp.time().replace(second=0, microsecond=0)
                    ),
                    member=member,
                    author=author,
                    site_user=site_user,
                    kind=kind,
                    amount=amount,
                    currency=currency,
                    orig_amount=q2(orig_amount) if currency == "USD" else None,
                    rate=D(rate) if currency == "USD" else None,
                    category=cat,
                    order=order,
                    order_ref=ref,
                    comment=(comment or "")[:2000],
                    receipt_file_id=receipt_file_id or "",
                    worker=(worker or "")[:255],
                    pay_type=(
                        (pay_type or "Avans")
                        if kind == OpKind.EXPENSE and cat.code == CAT_SALARY
                        else ""
                    ),
                    source=source,
                )
        except IntegrityError:
            if number:
                raise ServiceError(f"#{number} raqamli amal allaqachon bor.")
            continue
    raise ServiceError("Amalni saqlab bo'lmadi, qayta urinib ko'ring.")


STAFF_DAYS = 2  # staff may change/delete their own entries this many days back (canDelete_)


def _check_category_allowed(cat: FinanceCategory, actor_admin: bool):
    if cat.kind == CategoryKind.INTERNAL:
        raise ServiceError("O'tkazma faqat «Xodimga pul berish» orqali yoziladi.")
    if not actor_admin and (cat.code == CAT_FROM_BOSS or cat.admin_only):
        raise ServiceError("Bu kategoriyani faqat rahbar yoza oladi.")


def _check_date_allowed(on_date: date | None, actor_admin: bool):
    if actor_admin or on_date is None:
        return
    if not (today() - timedelta(days=STAFF_DAYS) <= on_date <= today()):
        raise ServiceError(f"Sanani faqat oxirgi {STAFF_DAYS} kun ichida tanlash mumkin.")


def can_modify(
    member: TelegramMember | None, op: Operation | None, admin: bool, edit: bool = False
) -> bool:
    """Admins: any row. Others: only what they booked themselves, at most 2 days old,
    and never the boss's «Rahbardan» money (canDelete_ in code.txt).

    edit=True (the site only — the bot has no edit): staff also can't change money a
    client paid («Pul oldim», others were already told the amount) or a transfer (the
    colleague's wallet would change behind their back). Deleting those stays allowed,
    as in the bot."""
    if not op or op.is_deleted:
        return False
    if admin:
        return True
    ok = bool(
        member
        and op.author_id == member.id
        and op.member_id == member.id
        and days_between(op.date, today()) <= STAFF_DAYS
        and op.category.code != CAT_FROM_BOSS
    )
    if ok and edit:
        is_collection = op.comment.startswith("Pul oldim") or bool(op.handover)
        ok = not is_collection and op.category.kind != CategoryKind.INTERNAL and not _pair_of(op)
    return ok


EDITABLE_FIELDS = {
    "amount",
    "currency",
    "orig_amount",
    "rate",
    "category_code",
    "order_ref",
    "comment",
    "worker",
    "pay_type",
    "date",
    "member",
    "kind",
}


def update_operation(
    op: Operation, data: dict, site_user: User | None = None, actor_admin: bool = False
) -> Operation:
    """Site edit of an operation. A transfer's other half follows amount/date; its
    kind, category and wallet can't change (the pair would stop matching)."""
    if op.is_deleted:
        raise ServiceError("O'chirilgan amalni tahrirlab bo'lmaydi.")
    unknown = set(data) - EDITABLE_FIELDS
    if unknown:
        raise ServiceError("Tahrirlab bo'lmaydigan maydon: " + ", ".join(sorted(unknown)))
    with transaction.atomic():
        op = Operation.objects.select_for_update().select_related("category").get(pk=op.pk)
        pair = _pair_of(op)
        if pair or op.category.kind == CategoryKind.INTERNAL:
            current = {"kind": op.kind, "category_code": op.category.code, "member": op.member_id}
            changed = [
                k
                for k, v in current.items()
                if k in data and (getattr(data[k], "pk", data[k])) != v
            ]
            if changed:
                raise ServiceError(
                    "O'tkazmaning turi, kategoriyasi va hamyoni o'zgarmaydi — o'chirib qaytadan yozing."
                )
        if "date" in data:
            _check_date_allowed(data["date"], actor_admin)
        if "kind" in data:
            op.kind = data["kind"]
        if "category_code" in data and data["category_code"] != op.category.code:
            cat = category(data["category_code"])
            if not cat:
                raise ServiceError("Kategoriya topilmadi.")
            _check_category_allowed(cat, actor_admin)
            op.category = cat
        if op.category.kind == CategoryKind.EXPENSE and op.kind != OpKind.EXPENSE:
            raise ServiceError("Bu kategoriya faqat chiqim uchun.")
        if op.category.kind == CategoryKind.INCOME and op.kind != OpKind.INCOME:
            raise ServiceError("Bu kategoriya faqat kirim uchun.")
        if "member" in data:
            op.member = data["member"]
        if "currency" in data:
            op.currency = data["currency"]
        if "orig_amount" in data:
            op.orig_amount = (
                q2(data["orig_amount"]) if data["orig_amount"] not in (None, "") else None
            )
        if "rate" in data:
            op.rate = D(data["rate"]) if data["rate"] not in (None, "") else None
        if op.currency == "USD":
            if not op.orig_amount or not op.rate:
                raise ServiceError("Dollar summasi va kursi kerak.")
            op.amount = q2(round(op.orig_amount * op.rate))
        else:
            op.orig_amount = op.rate = None
            if "amount" in data:
                op.amount = q2(data["amount"])
        if op.amount <= 0:
            raise ServiceError("Summa 0 dan katta bo'lishi kerak.")
        if "order_ref" in data:
            op.order_ref, op.order = _resolve_order(data["order_ref"])
        if "comment" in data:
            op.comment = (data["comment"] or "")[:2000]
        if "worker" in data:
            op.worker = (data["worker"] or "")[:255]
        if "pay_type" in data:
            op.pay_type = data["pay_type"] or ""
        if op.category.code != CAT_SALARY or op.kind != OpKind.EXPENSE:
            op.pay_type = ""
        if "date" in data and data["date"]:
            op.date = data["date"]
        op.site_user = site_user or op.site_user
        op.save()
        if pair:
            pair.amount, pair.currency, pair.orig_amount, pair.rate, pair.date = (
                op.amount,
                op.currency,
                op.orig_amount,
                op.rate,
                op.date,
            )
            pair.save(
                update_fields=["amount", "currency", "orig_amount", "rate", "date", "updated_at"]
            )
    return op


def _pair_of(op: Operation) -> Operation | None:
    if op.pair_id:
        return op.pair
    return Operation.objects.filter(pair=op).first()


def can_delete(member: TelegramMember | None, op: Operation | None) -> bool:
    """Bot rule: admins always, others their own recent entries."""
    return can_modify(member, op, bool(member and member.is_admin))


def delete_operation(op: Operation) -> list[Operation]:
    """Soft delete; a transfer is deleted on both sides. Returns what was deleted."""
    with transaction.atomic():
        deleted = []
        for t in [op, _pair_of(op)]:
            if t and not t.is_deleted:
                t.is_deleted = True
                t.deleted_at = now()
                t.save(update_fields=["is_deleted", "deleted_at", "updated_at"])
                deleted.append(t)
    return deleted


def restore_operation(op: Operation) -> Operation:
    if op.handover == "deleted":
        raise ServiceError(
            "Bu yozuvni rahbar «alohida kiritganman» deb o'chirgan — tiklansa pul ikki marta hisoblanadi."
        )
    with transaction.atomic():
        for t in [op, _pair_of(op)]:
            if t and t.is_deleted:
                t.is_deleted = False
                t.deleted_at = None
                t.save(update_fields=["is_deleted", "deleted_at", "updated_at"])
    return op


def create_transfer(
    *,
    sender: TelegramMember,
    receiver: TelegramMember,
    amount,
    comment: str = "",
    author: TelegramMember | None = None,
    order_ref: str = "",
    currency="UZS",
    orig_amount=None,
    rate=None,
    source="bot",
    site_user=None,
) -> tuple[Operation, Operation]:
    """trSave_ / handoverDo_: chiqim from one wallet + kirim into another, linked."""
    if not sender.has_wallet or not receiver.has_wallet:
        raise ServiceError("O'tkazma faqat hamyoni bor (tasdiqlangan) xodimlar o'rtasida bo'ladi.")
    if sender.pk == receiver.pk:
        raise ServiceError("O'zingizga o'tkazib bo'lmaydi.")
    with transaction.atomic():
        out = create_operation(
            internal=True,
            member=sender,
            author=author or sender,
            kind=OpKind.EXPENSE,
            amount=amount,
            category_code=CAT_TRANSFER,
            comment=comment,
            worker=receiver.name,
            order_ref=order_ref,
            currency=currency,
            orig_amount=orig_amount,
            rate=rate,
            source=source,
            site_user=site_user,
        )
        inc = create_operation(
            internal=True,
            member=receiver,
            author=author or sender,
            kind=OpKind.INCOME,
            amount=amount,
            category_code=CAT_TRANSFER,
            comment=f"#{out.number}" + (f": {comment}" if comment else ""),
            worker=sender.name,
            order_ref=order_ref,
            currency=currency,
            orig_amount=orig_amount,
            rate=rate,
            source=source,
            site_user=site_user,
        )
        inc.pair = out
        inc.save(update_fields=["pair"])
    return out, inc


def balance(member: TelegramMember, until: date | None = None) -> Decimal:
    qs = Operation.objects.filter(member=member, is_deleted=False)
    if until:
        qs = qs.filter(date__lte=until)
    agg = qs.aggregate(
        inc=Sum("amount", filter=Q(kind=OpKind.INCOME)),
        exp=Sum("amount", filter=Q(kind=OpKind.EXPENSE)),
    )
    return (agg["inc"] or ZERO) - (agg["exp"] or ZERO)


def balances() -> dict[int, Decimal]:
    rows = (
        Operation.objects.filter(is_deleted=False)
        .values("member_id")
        .annotate(
            inc=Sum("amount", filter=Q(kind=OpKind.INCOME)),
            exp=Sum("amount", filter=Q(kind=OpKind.EXPENSE)),
        )
    )
    return {r["member_id"]: (r["inc"] or ZERO) - (r["exp"] or ZERO) for r in rows}


def last_day(member: TelegramMember) -> date | None:
    return Operation.objects.filter(member=member, is_deleted=False).aggregate(m=Max("date"))["m"]


# =================================================================== company totals
def is_company_expense(op: Operation, scope_all=True) -> bool:
    """expOf_: for the whole company internal moves and personal spending are not
    expenses; inside one wallet only transfers are excluded."""
    if op.kind != OpKind.EXPENSE:
        return False
    return not op.category.excluded if scope_all else op.category.code != CAT_TRANSFER


def is_company_income(op: Operation, scope_all=True) -> bool:
    if op.kind != OpKind.INCOME:
        return False
    return not op.category.excluded if scope_all else op.category.code != CAT_TRANSFER


def period_ops(start: date | None, end: date | None, member: TelegramMember | None = None):
    qs = Operation.objects.filter(is_deleted=False).select_related("category", "member")
    if start:
        qs = qs.filter(date__gte=start)
    if end:
        qs = qs.filter(date__lte=end)
    if member:
        qs = qs.filter(member=member)
    return qs


def summary(start: date | None, end: date | None, member: TelegramMember | None = None) -> dict:
    """Totals for «📊 Ma'lumot» and the site dashboard (info_ / buildDashboard_)."""
    scope_all = member is None
    rows = list(period_ops(start, end, member))
    exp = sum((t.amount for t in rows if is_company_expense(t, scope_all)), ZERO)
    inc = sum((t.amount for t in rows if is_company_income(t, scope_all)), ZERO)

    def group(pred):
        g: dict[str, dict] = {}
        for t in rows:
            if not pred(t):
                continue
            c = t.category
            x = g.setdefault(
                c.code,
                {
                    "code": c.code,
                    "name": c.name,
                    "emoji": c.emoji,
                    "color": c.color,
                    "sum": ZERO,
                    "n": 0,
                },
            )
            x["sum"] += t.amount
            x["n"] += 1
        return sorted(g.values(), key=lambda x: -x["sum"])

    def total(pred):
        return sum((t.amount for t in rows if pred(t)), ZERO)

    salary: dict[str, Decimal] = {}
    for t in rows:
        if t.kind == OpKind.EXPENSE and t.category.code == CAT_SALARY:
            k = t.worker or "— (ism yozilmagan)"
            salary[k] = salary.get(k, ZERO) + t.amount
    return {
        "expense": exp,
        "income": inc,
        "balance": inc - exp,
        "given_to_staff": total(
            lambda t: t.kind == OpKind.INCOME and t.category.code == CAT_FROM_BOSS
        ),
        "boss_personal": total(
            lambda t: t.kind == OpKind.EXPENSE and t.category.code == "rahbarga"
        ),
        "home": total(lambda t: t.kind == OpKind.EXPENSE and t.category.code == "uy"),
        "transfers": total(lambda t: t.kind == OpKind.EXPENSE and t.category.code == CAT_TRANSFER),
        "expense_by_category": group(lambda t: is_company_expense(t, scope_all)),
        "income_by_category": group(lambda t: is_company_income(t, scope_all)),
        "salary_by_worker": sorted(salary.items(), key=lambda kv: -kv[1]),
        "count": len(rows),
    }


def months_series(member: TelegramMember | None = None, months: int = 7) -> list[dict]:
    out = []
    for k in range(-(months - 1), 1):
        ym = add_months(today().strftime("%Y-%m"), k)
        s, e = month_bounds(ym)
        sm = summary(s, e, member)
        out.append(
            {"month": ym, "label": month_name(ym), "income": sm["income"], "expense": sm["expense"]}
        )
    return out


# =================================================================== money requests
def create_request(member: TelegramMember, m: dict, reason: str = "") -> MoneyRequest:
    for _ in range(5):
        try:
            with transaction.atomic():
                return MoneyRequest.objects.create(
                    number=_next_number(MoneyRequest),
                    member=member,
                    amount=m["amount"],
                    currency=m["cur"],
                    orig_amount=m.get("orig"),
                    rate=m.get("rate"),
                    reason=(reason or "")[:300],
                )
        except IntegrityError:
            continue
    raise ServiceError("So'rovni saqlab bo'lmadi.")


def give_request(
    req: MoneyRequest, by: TelegramMember | None, m: dict, site_user=None
) -> Operation:
    """reqGive_: the boss gave the money → kirim «Rahbardan» into the wallet."""
    with transaction.atomic():
        req = MoneyRequest.objects.select_for_update().get(pk=req.pk)
        if req.status != "pending":
            raise ServiceConflict("Bu so'rovga allaqachon javob berilgan.")
        op = create_operation(
            internal=True,
            member=req.member,
            author=by,
            kind=OpKind.INCOME,
            amount=m["amount"],
            category_code=CAT_FROM_BOSS,
            currency=m["cur"],
            orig_amount=m.get("orig"),
            rate=m.get("rate"),
            comment=f"So'rov #{req.number}" + (f": {req.reason}" if req.reason else ""),
            source="site" if site_user else "bot",
            site_user=site_user,
        )
        req.status = "given"
        req.answer = "berildi " + (
            f"{num(m.get('orig'))}$" if m["cur"] == "USD" else num(m["amount"])
        )
        req.answered_by = by
        req.operation = op
        req.answered_at = now()
        req.save()
    return op


def reject_request(req: MoneyRequest, by: TelegramMember | None) -> MoneyRequest:
    with transaction.atomic():
        req = MoneyRequest.objects.select_for_update().get(pk=req.pk)
        if req.status != "pending":
            raise ServiceConflict("Bu so'rovga allaqachon javob berilgan.")
        req.status = "rejected"
        req.answer = "rad etildi"
        req.answered_by = by
        req.answered_at = now()
        req.save()
    return req


# =================================================================== month report
def month_for_report() -> str:
    t = today()
    return add_months(t.strftime("%Y-%m"), -1) if t.day <= 5 else t.strftime("%Y-%m")


def month_summary(member: TelegramMember, ym: str) -> dict:
    s, e = month_bounds(ym)
    rows = list(period_ops(s, e, member))
    inc = sum((t.amount for t in rows if t.kind == OpKind.INCOME), ZERO)
    out = sum((t.amount for t in rows if t.kind == OpKind.EXPENSE), ZERO)
    opening = balance(member, s - timedelta(days=1))
    return {
        "month": ym,
        "opening": opening,
        "income": inc,
        "expense": out,
        "closing": opening + inc - out,
        "count": len(rows),
    }


def submit_month(member: TelegramMember, ym: str, note: str = "") -> MonthReport:
    sm = month_summary(member, ym)
    rep, _ = MonthReport.objects.update_or_create(
        member=member,
        month=ym,
        defaults={"submitted_at": now(), "balance": sm["closing"], "note": (note or "")[:300]},
    )
    return rep


# =================================================================== bonus («Готов»)
def bonus_percent(days: int) -> Decimal:
    for limit, pct in BONUS_TIERS:
        if days <= limit:
            return D(pct)
    return ZERO


def bonus_tolerance(cur: str) -> Decimal:
    return D("0.5") if cur == "USD" else D(1000)


def money_state(b: OrderBonus) -> dict:
    """Paid / rest of a Готов order (moneyState_): the site's «Полученная сумма»;
    «💰 Pul oldim» entries the site doesn't show yet lower the rest further."""
    info = order_info(b.order_ref)
    if info and info.order and info.paid is not None:
        rest = info.rest if info.rest is not None else max(ZERO, b.total - info.paid)
        if b.rest_base is not None:
            rest = min(rest, max(ZERO, b.rest_base - (b.got or ZERO)))
        return {"paid": max(ZERO, b.total - rest), "rest": rest, "src": "sayt"}
    paid = ZERO
    rate = usd_rate()
    for t in Operation.objects.filter(
        order_ref=b.order_ref,
        kind=OpKind.INCOME,
        is_deleted=False,
        category__code__in=[CAT_ADVANCE, CAT_REST],
    ):
        if b.currency != "USD":
            paid += t.amount
        else:
            paid += t.orig_amount if t.currency == "USD" else (t.amount / rate if rate else ZERO)
    paid = q2(paid)
    return {"paid": paid, "rest": max(ZERO, b.total - paid), "src": "bot"}


def bonus_start(info: OrderInfo, ready: date) -> tuple[OrderBonus, bool]:
    b, created = OrderBonus.objects.get_or_create(
        order_ref=info.ref,
        defaults=dict(
            order=info.order,
            client=info.client[:255],
            description=info.furniture[:255],
            phone=info.phone[:64],
            total=info.total,
            currency=info.currency,
            ready_date=ready,
            receiver=", ".join(m.name for m in duty_members("is_bonus_receiver"))[:255],
        ),
    )
    return b, created


def _lock_waiting_bonus(b: OrderBonus) -> OrderBonus:
    """Re-read under a lock: the scheduler (expiry) and a «Pul oldim» press can race."""
    locked = OrderBonus.objects.select_for_update().get(pk=b.pk)
    if locked.status != "waiting":
        raise ServiceConflict("Bu zakaz bo'yicha bonus allaqachon yopilgan.")
    return locked


@transaction.atomic
def bonus_finish(b: OrderBonus, how: str) -> OrderBonus:
    """bonusDone_: the client paid everything — fix the days, percent and bonus."""
    b = _lock_waiting_bonus(b)
    d = max(0, days_between(b.ready_date, today()))
    pct = bonus_percent(d)
    som = b.total * usd_rate() if b.currency == "USD" else b.total
    b.status, b.paid_date, b.days, b.percent = "done", today(), d, pct
    b.bonus = q2(round(som * pct / 100))
    b.rest = ZERO
    b.note = how[:255]
    b.save()
    return b


@transaction.atomic
def bonus_expire(b: OrderBonus, rest) -> OrderBonus:
    b = _lock_waiting_bonus(b)
    b.status = "expired"
    b.days = days_between(b.ready_date, today())
    b.percent, b.bonus, b.rest = ZERO, ZERO, rest
    b.note = "30 kundan o'tdi"
    b.save()
    return b


def bonus_collect(b: OrderBonus, collector: TelegramMember, m: dict, full: bool) -> dict:
    """«💰 Pul oldim»: the collector took (part of) the rest from the client. Books a
    kirim «Qoldiq» into the collector's wallet and recomputes the rest."""
    with transaction.atomic():
        b = OrderBonus.objects.select_for_update().get(pk=b.pk)
        if b.status != "waiting":
            raise ServiceConflict("Bu zakaz bo'yicha bonus allaqachon yopilgan.")
        before = money_state(b)
        if b.rest_base is None:
            b.rest_base, b.got = before["rest"], ZERO
        rate = usd_rate() or D(1)
        in_cur = (
            (m["orig"] if m["cur"] == "USD" else m["amount"] / rate)
            if b.currency == "USD"
            else m["amount"]
        )
        b.got = q2((b.got or ZERO) + in_cur)
        piece = f"{num(m['orig'])}$" if m["cur"] == "USD" else num(m["amount"])
        b.got_text = ((b.got_text + " + ") if b.got_text else "") + piece
        b.save()
        op = create_operation(
            internal=True,
            member=collector,
            author=collector,
            kind=OpKind.INCOME,
            amount=m["amount"],
            category_code=CAT_REST,
            currency=m["cur"],
            orig_amount=m.get("orig"),
            rate=m.get("rate"),
            order_ref=b.order_ref,
            comment="Pul oldim (mijozdan qoldiq)",
        )
        after = money_state(b)
        b.rest = after["rest"]
        b.note = f"Olindi: {b.got_text}"
        b.save()
        done = full or after["rest"] <= bonus_tolerance(b.currency)
        if done:
            b = bonus_finish(
                b,
                ("To'liq oldi: " if full else "Qismlab oldi: ")
                + f"{collector.name} · {b.got_text}",
            )
    return {"bonus": b, "operation": op, "rest": after["rest"], "full": done}


# =================================================================== warranty / site entry / feedback
def warranty_ensure(ref: str, client: str, ready: date | None) -> WarrantyLetter:
    w, _ = WarrantyLetter.objects.get_or_create(
        order_ref=ref, defaults={"client": client[:255], "ready_date": ready}
    )
    return w


def warranty_give(ref: str, by_name: str) -> WarrantyLetter:
    ref = str(ref).lstrip("#").strip()
    info = order_info(ref)
    with transaction.atomic():
        w = WarrantyLetter.objects.select_for_update().filter(order_ref=ref).first()
        if not w and not info:
            raise ServiceError(f"{ref} zakazi topilmadi.")
        if w and w.given:
            raise ServiceConflict(
                f"{ref} · {w.client} — kafolat xati allaqachon berilgan ({ddmm(w.given_at)})."
            )
        if not w:
            w = WarrantyLetter(
                order_ref=ref, client=info.client[:255], ready_date=info.ready_date or today()
            )
        w.given, w.given_at, w.given_by = True, today(), by_name[:255]
        if info and not w.client:
            w.client = info.client[:255]
        try:
            w.save()
        except IntegrityError:  # two first-time presses at once
            raise ServiceConflict(f"{ref} — kafolat xati allaqachon berilgan.")
    return w


def site_entry_create(
    ref: str, client: str, sum_text: str, taken_by: str, rest_text: str
) -> SiteEntryTask:
    code = "sk" + format(int(now().timestamp() * 1000), "x")
    while SiteEntryTask.objects.filter(code=code).exists():
        code += "x"
    return SiteEntryTask.objects.create(
        code=code,
        date=today(),
        order_ref=ref,
        client=client[:255],
        sum_text=sum_text[:255],
        taken_by=taken_by[:255],
        rest_text=rest_text[:255],
    )


def site_entry_done(task: SiteEntryTask, by_name: str) -> SiteEntryTask:
    with transaction.atomic():
        task = SiteEntryTask.objects.select_for_update().get(pk=task.pk)
        if task.is_done:
            raise ServiceConflict("Bu allaqachon belgilangan.")
        task.is_done, task.done_at, task.done_by = True, today(), by_name[:255]
        task.save()
    return task


def feedback_schedule(info: OrderInfo, ready: date) -> ClientFeedback:
    fb, _ = ClientFeedback.objects.get_or_create(
        order_ref=info.ref,
        defaults={"client": info.client[:255], "phone": info.phone[:64], "ready_date": ready},
    )
    return fb


def feedback_receive(
    fb: ClientFeedback, by_name: str, text: str, file_id: str = "", url: str = ""
) -> ClientFeedback:
    fb.status, fb.received_date, fb.received_by = "received", today(), by_name[:255]
    fb.text = (text or "")[:2000]
    fb.screenshot_file_id = file_id or fb.screenshot_file_id
    fb.screenshot_url = url or fb.screenshot_url
    fb.save()
    return fb


# =================================================================== handover
def handover_pending():
    return list(
        Operation.objects.filter(
            kind=OpKind.INCOME,
            category__code=CAT_REST,
            comment__startswith="Pul oldim",
            is_deleted=False,
            handover="",
        )
        .select_related("member", "category", "author")
        .order_by("date", "number")
    )


def _lock_handover(op: Operation) -> Operation:
    op = Operation.objects.select_for_update().select_related("category").get(pk=op.pk)
    if not (
        op.kind == OpKind.INCOME
        and op.category.code == CAT_REST
        and op.comment.startswith("Pul oldim")
    ):
        raise ServiceError("Bu yozuv mijozdan olingan «Pul oldim» puli emas.")
    if op.is_deleted or op.handover:
        raise ServiceConflict(f"#{op.number} allaqachon belgilangan.")
    return op


def handover_accept(op: Operation, boss: TelegramMember) -> tuple[Operation, Operation]:
    """The collector handed the cash to the boss: transfer collector → boss."""
    if not boss.is_admin:
        raise ServiceForbidden("Pulni faqat rahbar qabul qiladi.")
    with transaction.atomic():
        op = _lock_handover(op)
        info = order_info(op.order_ref)
        com = (
            f"Rahbarga topshirdi: {op.order_ref}"
            + (f" · {info.client}" if info else "")
            + f" (#{op.number})"
        )
        pair = create_transfer(
            sender=op.member,
            receiver=boss,
            amount=op.amount,
            comment=com,
            author=boss,
            order_ref=op.order_ref,
            currency=op.currency,
            orig_amount=op.orig_amount,
            rate=op.rate,
        )
        op.handover = "accepted"
        op.save(update_fields=["handover", "updated_at"])
    return pair


def handover_drop(op: Operation) -> Operation:
    """The boss booked this money separately — delete the collector's row."""
    with transaction.atomic():
        op = _lock_handover(op)
        op.is_deleted, op.deleted_at, op.handover = True, now(), "deleted"
        op.save(update_fields=["is_deleted", "deleted_at", "handover", "updated_at"])
    return op


# =================================================================== checks (🔍 Tekshiruv)
def checks() -> list[dict]:
    """checks_: problems an accountant should look at, worst first."""
    out: list[dict] = []

    def add(lv, title, detail, fix):
        out.append({"level": lv, "title": title, "detail": detail, "fix": fix})

    t0 = today()
    since = month_bounds(add_months(t0.strftime("%Y-%m"), -2))[0]
    recent = list(period_ops(since, None))
    bal = balances()
    st = staff()
    for u in st:
        b = bal.get(u.id, ZERO)
        if b < 0:
            add(
                "h",
                f"{u.name}: hamyon manfiy ({money(b)})",
                "Xodim berilgan puldan ko'proq xarajat yozgan.",
                "Kirim yozilmay qolgan bo'lishi mumkin — so'rang va «💸 Pul berish» orqali kiriting yoki xato chiqimni o'chiring.",
            )
    for ym in [t0.strftime("%Y-%m"), add_months(t0.strftime("%Y-%m"), -1)]:
        s, e = month_bounds(ym)
        sm = summary(s, e)
        if sm["expense"] > sm["income"] and sm["expense"] > 0:
            add(
                "h",
                f"{month_name(ym)}: xarajat daromaddan {money(sm['expense'] - sm['income'])} ko'p",
                f"Daromad {money(sm['income'])}, xarajat {money(sm['expense'])}.",
                "«🧾 Buyurtmalar»da mijoz qarzlarini ko'ring va undiring; eng katta xarajat turini «📊 Ma'lumot»da tekshiring.",
            )
    for t in recent:
        if t.kind == OpKind.EXPENSE and t.category.needs_order and not t.order_ref:
            add(
                "m",
                f"#{t.number} {t.member.name}: {t.category.name} buyurtmasiz",
                f"{ddmm(t.date)} · {money(t.amount)} · {t.comment}",
                "Qaysi mijoz uchun olinganini aniqlang — aks holda buyurtma foydasi noto'g'ri chiqadi.",
            )
    seen: dict[tuple, list] = {}
    for t in recent:
        if t.kind == OpKind.EXPENSE:
            seen.setdefault((t.member_id, t.date, t.amount, t.category_id), []).append(t)
    for g in seen.values():
        if len(g) > 1:
            add(
                "m",
                f"{g[0].member.name}: bir xil yozuv {len(g)} marta",
                f"{ddmm(g[0].date)} · {money(g[0].amount)} · {g[0].category.name} · "
                + ", ".join(f"#{t.number}" for t in g),
                "Ikki marta kiritilgan bo'lsa, ortiqchasini o'chiring (/ochir raqam).",
            )
    warn = int(config.FIN_WARN_PERCENT or 80)
    refs = set(
        Operation.objects.filter(is_deleted=False)
        .exclude(order_ref="")
        .values_list("order_ref", flat=True)
    )
    infos = order_infos(refs)
    stats = order_stats_bulk(refs)
    for ref in sorted(refs, key=lambda r: (not r.isdigit(), int(r) if r.isdigit() else 0, r)):
        info = infos.get(ref)
        if not info or not info.price_uzs:
            continue
        stt = stats.get(ref, {"spent": ZERO})
        pct = round(stt["spent"] * 100 / info.price_uzs)
        if stt["spent"] > info.price_uzs:
            add(
                "h",
                f"{ref} ({info.client}): xarajat shartnomadan oshdi",
                f"Shartnoma {money(info.price_uzs)}, sarflandi {money(stt['spent'])} ({pct}%)",
                "Xarajatlarni ko'rib chiqing; qo'shimcha ish bo'lsa mijoz bilan narxni qayta kelishing.",
            )
        elif pct >= warn and info.bucket == "jarayonda":
            add(
                "m",
                f"{ref} ({info.client}): byudjetning {pct}% sarflandi",
                f"Qoldi: {money(info.price_uzs - stt['spent'])}",
                "Qolgan ishlar shu summaga sig'ishini tekshiring.",
            )
    pm = add_months(t0.strftime("%Y-%m"), -1)
    pms, pme = month_bounds(pm)
    submitted = set(MonthReport.objects.filter(month=pm).values_list("member_id", flat=True))
    for u in st:
        b, last = bal.get(u.id, ZERO), last_day(u)
        if b > 0 and last and days_between(last, t0) >= 3:
            add(
                "l",
                f"{u.name}: {days_between(last, t0)} kundan beri yozuv yo'q",
                f"Qo'lida {money(b)} turibdi.",
                "Xarajatlarni kiritishni so'rang (👛 Hamyonlar → 🔔).",
            )
        if t0.day > 3 and u.id not in submitted and period_ops(pms, pme, u).exists():
            add(
                "m",
                f"{u.name}: {month_full(pm)} hisobi topshirilmagan",
                "Oylik hisob tasdiqlanmagan.",
                "Xodimga eslatma yuboring (👛 Hamyonlar → 🔔).",
            )
    no_com = [
        t
        for t in recent
        if t.kind == OpKind.EXPENSE
        and not t.comment.strip()
        and t.category.code in ("boshqa", "usluga")
    ]
    if no_com:
        add(
            "l",
            f"{len(no_com)} ta «Boshqa/Usluga» chiqim izohsiz",
            ", ".join(f"#{t.number}" for t in no_com[:8]),
            "Nimaga sarflanganini izohda yozish talab qilinsin.",
        )
    order = {"h": 0, "m": 1, "l": 2}
    return sorted(out, key=lambda x: order[x["level"]])


def fmt_order_money(info: OrderInfo, v) -> str:
    return f"{fmt_cur(v, info.currency)} {cur_name(info.currency)}"


# =================================================================== bot-facing rules
# Rules the Telegram bot used to hold inline (accounting/telegram/router.py); the bot
# now calls them through api/views/bot/finance.py. The site uses them too.
def touch_member_username(telegram_id, username: str) -> TelegramMember | None:
    """_sync_profile: keep the Telegram username fresh."""
    m = member_by_tg(telegram_id)
    username = username or ""
    if m and username != m.username:
        m.username = username[:255]
        m.save(update_fields=["username", "updated_at"])
    return m


def rename_member(member: TelegramMember, name: str) -> TelegramMember:
    name = (name or "").strip()[:255]
    if not name:
        raise ServiceError("Ism bo'sh bo'lishi mumkin emas.")
    member.name = name
    member.save(update_fields=["name", "updated_at"])
    return member


def set_usd_rate(rate) -> Decimal:
    """/kurs: 0 = use the Central Bank rate."""
    try:
        value = D(str(rate).replace(",", ".").replace(" ", ""))
    except Exception:  # noqa: BLE001 — Decimal parse errors
        raise ServiceError("Kursni raqam bilan yozing, masalan: 12050")
    if value < 0 or value > 1_000_000:
        raise ServiceError("Kurs 0 dan 1 000 000 gacha bo'lishi kerak.")
    config.FIN_USD_RATE = float(value)
    return value


def set_report_template(content: bytes) -> str:
    """/shablon: background picture of the payment sheet (report_card_png)."""
    if not content:
        raise ServiceError("Rasm bo'sh.")
    path = default_storage.save("finance/report_background.png", ContentFile(content))
    config.FIN_REPORT_TEMPLATE = path
    return path


def reset_report_template() -> None:
    config.FIN_REPORT_TEMPLATE = ""


def duty_recipients(duty: str) -> tuple[list[TelegramMember], bool]:
    """Who holds `duty`; if nobody does, the admins and fallback=True (notifyTo_)."""
    members = duty_members(duty)
    if members:
        return members, False
    return admins(), True


def create_operation_as(actor: TelegramMember, target: TelegramMember, **fields) -> Operation:
    """The bot's booking rule: only active, non-task-only members book money, and only
    admins book into somebody else's wallet. `actor_admin` always comes from the actor."""
    if not actor.is_active_member or actor.is_task_only:
        raise ServiceForbidden("Siz kirim-chiqim kirita olmaysiz.")
    if target.pk != actor.pk and not actor.is_admin:
        raise ServiceForbidden("Faqat o'z hamyoningizga yozishingiz mumkin.")
    if not target.is_active_member:
        raise ServiceError("Xodim topilmadi.")
    for spoofable in ("actor_admin", "author", "member", "internal"):
        fields.pop(spoofable, None)
    if fields.get("category_code") == CAT_SALARY and not actor.is_admin:
        fields["pay_type"] = "Avans"  # only the boss chooses avans / oylik
    if fields.get("currency") == "USD":  # the amount is orig * rate, never what the client says
        rate = usd_rate()  # the server's rate, never the client's
        if not fields.get("orig_amount") or not rate:
            raise ServiceError("Dollar summasi va kursi kerak.")
        fields["rate"] = rate
        fields["amount"] = q2(round(D(fields["orig_amount"]) * rate))
    return create_operation(member=target, author=actor, actor_admin=actor.is_admin, **fields)


def attach_receipt(op: Operation, file_id: str, actor: TelegramMember) -> Operation:
    """Receipt photo on an existing entry: the author or an admin."""
    if op.is_deleted:
        raise ServiceError("O'chirilgan amalga chek qo'shib bo'lmaydi.")
    if not (actor.is_admin or (actor.is_active_member and op.author_id == actor.pk)):
        raise ServiceForbidden("Bu amalga chek qo'sha olmaysiz.")
    if not file_id:
        raise ServiceError("Chek rasmi yuborilmadi.")
    op.receipt_file_id = file_id
    op.save(update_fields=["receipt_file_id", "updated_at"])
    return op


def delete_operation_as(actor: TelegramMember, number: int) -> list[Operation]:
    op = (
        Operation.objects.select_related("member", "category", "author")
        .filter(number=number)
        .first()
    )
    if not op:
        raise ServiceError(f"#{number} amal topilmadi.")
    if not can_delete(actor, op):
        raise ServiceForbidden(
            "Bu amalni o'chira olmaysiz (sizniki emas yoki 2 kundan eski — rahbarga murojaat qiling)."
        )
    return delete_operation(op)


def request_money(member: TelegramMember, amount_text: str, reason: str = "") -> MoneyRequest:
    """«Rahbardan pul so'rash»: parse the amount and open a request."""
    if not member.has_wallet:
        raise ServiceForbidden("Pul so'rash faqat hamyoni bor xodimlar uchun.")
    return create_request(member, money_in(amount_text), reason)


def request_amount(req: MoneyRequest, amount_text: str | None = None) -> dict:
    """The money a «give» books: what the boss typed, else the requested amount."""
    text = str(amount_text or "").strip()
    if text:
        return money_in(text)
    if req.currency == "USD":
        return money_in(f"{req.orig_amount}$")
    return {"amount": req.amount, "cur": "UZS", "orig": None, "rate": None}


def set_request_messages(req: MoneyRequest, messages) -> MoneyRequest:
    """Remember the admins' message ids so the answer can edit them."""
    try:
        clean = [[int(c), int(m)] for c, m in (messages or [])]
    except (TypeError, ValueError):
        raise ServiceError("Xabar identifikatorlari noto'g'ri.")
    req.admin_messages = clean
    req.save(update_fields=["admin_messages"])
    return req


def month_report_target(member: TelegramMember) -> str:
    """Which month «Oylik hisob» offers: the one to report, or the current month when
    last month is already submitted."""
    ym = month_for_report()
    cur = today().strftime("%Y-%m")
    if ym != cur and MonthReport.objects.filter(member=member, month=ym).exists():
        ym = cur
    return ym


def wallets_overview() -> dict:
    """«Hamyonlar»: every wallet with balance, last entry day, report flag and the
    month's spending, plus pending join requests. (Per-member queries on purpose:
    a dozen wallets.)"""
    ym = today().strftime("%Y-%m")
    s, e = month_bounds(ym)
    rep_month = month_for_report()
    bal = balances()
    reported = set(MonthReport.objects.filter(month=rep_month).values_list("member_id", flat=True))
    rows, total = [], ZERO
    for u in wallets():
        bv = bal.get(u.id, ZERO)
        if u.role == TelegramRole.STAFF:
            total += bv
        spent = sum((t.amount for t in period_ops(s, e, u) if t.kind == OpKind.EXPENSE), ZERO)
        rows.append(
            {
                "member": u,
                "balance": bv,
                "last_day": last_day(u),
                "reported": u.id in reported,
                "month_spent": spent,
            }
        )
    pending = list(TelegramMember.objects.filter(role=TelegramRole.PENDING).select_related("user"))
    return {"report_month": rep_month, "rows": rows, "pending": pending, "staff_total": total}


def set_manual_price(ref: str, price_text: str) -> ManualOrder:
    """Change the contract price of a hand-made order."""
    mo = ManualOrder.objects.filter(ref__iexact=str(ref).strip()).first()
    if not mo:
        raise ServiceError("Bu qo'lda kiritilgan buyurtma emas.")
    mo.price = money_in(price_text)["amount"]
    mo.save(update_fields=["price"])
    return mo


def toggle_manual_order(ref: str) -> ManualOrder:
    """Close / reopen a hand-made order."""
    mo = ManualOrder.objects.filter(ref__iexact=str(ref).strip()).first()
    if not mo:
        raise ServiceError("Bu qo'lda kiritilgan buyurtma emas.")
    mo.is_closed = not mo.is_closed
    mo.closed = today() if mo.is_closed else None
    mo.save(update_fields=["is_closed", "closed"])
    return mo


def bonus_collect_flow(
    ref: str, collector: TelegramMember, amount_text: str, full: bool = False
) -> dict:
    """«Pul oldim» end to end: parse the amount, book the money, update the bonus and
    open the «Saytga kiritish» task - one transaction."""
    with transaction.atomic():
        bn = OrderBonus.objects.filter(order_ref=str(ref), status="waiting").first()
        if not bn:
            raise ServiceConflict("Bu zakaz bo'yicha bonus allaqachon yopilgan.")
        m = money_in(amount_text)
        res = bonus_collect(bn, collector, m, full)
        bn = res["bonus"]
        cur = bn.currency
        rest_text = "0" if res["full"] else f"{fmt_cur(res['rest'], cur)} {cur_name(cur)}"
        sum_text = money_text(m)
        task = site_entry_create(bn.order_ref, bn.client, sum_text, collector.name, rest_text)
    return {**res, "task": task, "sum_text": sum_text, "rest_text": rest_text}


def bonus_close(ref: str, who: str) -> OrderBonus:
    """«Zakazni yopish»: only when the client owes nothing."""
    bn = OrderBonus.objects.filter(order_ref=str(ref), status="waiting").first()
    if not bn:
        raise ServiceConflict(
            f"{ref} zakazi bo'yicha bonus allaqachon yopilgan (yoki 30 kundan o'tgan)."
        )
    ms = money_state(bn)
    if ms["rest"] > bonus_tolerance(bn.currency):
        raise ServiceError(
            f"Qoldiq hali {fmt_cur(ms['rest'], bn.currency)} {cur_name(bn.currency)} — zakazni "
            "faqat qoldiq 0 bo'lganda yopish mumkin. Olgan pulingizni «Pul oldim» orqali kiriting."
        )
    return bonus_finish(bn, f"Yopdi: {who}" + (f" · olingan: {bn.got_text}" if bn.got_text else ""))


def receive_feedback_photo(
    ref: str, by_name: str, caption: str, file_id: str, content: bytes | None
) -> ClientFeedback:
    """«Fikr oldim»: the screenshot of the client's feedback. Creates the feedback row
    when the order never got one, stores the picture and marks it received."""
    import re

    ref = str(ref).strip().lstrip("#")
    with transaction.atomic():
        fb = ClientFeedback.objects.select_for_update().filter(order_ref=ref).first()
        if fb is None:
            info = order_info(ref)
            fb = ClientFeedback.objects.create(
                order_ref=ref, client=(info.client if info else "")[:255], status="asked"
            )
        if fb.status == "received":
            raise ServiceConflict(f"{ref} — fikr allaqachon olingan.")
        url = ""
        if content:
            path = default_storage.save(
                f"finance/feedback/{re.sub(r'[^0-9A-Za-z_-]', '_', fb.order_ref)}.jpg",
                ContentFile(content),
            )
            url = default_storage.url(path)
        return feedback_receive(fb, by_name, (caption or "")[:300], file_id, url)
