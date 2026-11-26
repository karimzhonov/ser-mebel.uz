"""Stage 3 — umumiy xarajat (overhead) and «Foyda yechish». Source of truth; the API
only calls these. Owner's rules (2026-11-25):

* Overhead of a month = what belongs to no single client:
    - wallet expenses without an order ID (company categories only — «excluded»
      ones like «Foyda yechish», «Omborga xarid» (stock: a client's cost when given
      out of the warehouse) or transfers never count), minus «↩️ Qaytim» without
      an ID;
    - the company cars (FinanceCar.is_overhead): every expense whose «Kimga /
      mashina» is such a car, even with an order ID (from FIN_OVERHEAD_SINCE on —
      such an expense then leaves the order's «spent», see car_op_ids);
    - salaries: an approved salary sheet's part that is not on any ID (fiksa,
      oklad, Instagram − fines; the ID part is already on the clients). People with
      no approved sheet that month (and every month before FIN_OVERHEAD_SINCE, when
      the sheets were in Excel) count with their wallet «Oylik» payments;
    - the boss's fixed salary (FIN_BOSS_SALARY). His own wallet salary rows never
      count: anything he takes above it is a profit withdrawal.
* Rate for an order that became Готов in month M = overhead of the 3 whole months
  before M ÷ contract sums (so'm) of the orders that became Готов in those months.
  Share = contract × rate, written once (OrderOverhead) and never recomputed.
* The share is NOT in the order's «spent» (that stays the direct cost); the order
  shows gross profit (contract − spent) and net profit (− the share).
* Every month shows what was really spent on overhead against the shares the
  orders took (the rate is set in advance, so they never match exactly); the
  difference is counted when the profit that may be taken out is worked out.
* «Foyda yechish»: only the net profit of orders that became Готов from
  FIN_OVERHEAD_SINCE on AND are paid in full, minus that difference, minus what was
  already taken out; never more than the wallet it is taken from holds.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from constance import config
from django.db import IntegrityError, transaction
from django.db.models import Sum

from core.exceptions import ServiceError

from . import services as S
from .constants import CAT_PROFIT, CAT_REFUND, CAT_SALARY, CategoryKind, OpKind, PayType
from .models import (
    FinanceCar,
    FinanceCategory,
    ManualOrder,
    Operation,
    OrderBonus,
    OrderOverhead,
    Worker,
)
from .text import add_months, month_bounds, month_name, today

ZERO = Decimal(0)
WINDOW_MONTHS = 3
DEFAULT_SINCE = date(2026, 12, 1)


def D(v) -> Decimal:
    return S.D(v)


def q2(v) -> Decimal:
    return S.q2(v)


def since() -> date:
    """FIN_OVERHEAD_SINCE, always the 1st of its month (the rules switch per whole month:
    a mid-month date would take company-car costs off the orders without adding them to
    any month's overhead)."""
    try:
        d = date.fromisoformat(str(config.FIN_OVERHEAD_SINCE or "")[:10])
    except ValueError:
        d = DEFAULT_SINCE
    return d.replace(day=1)


def _som(v) -> str:
    return f"{int(q2(v)):,} so'm".replace(",", " ")


def ym_of(d: date) -> str:
    return d.strftime("%Y-%m")


# ------------------------------------------------------------------ company cars
def _car_keys() -> set[str]:
    """«Kimga / mashina» spellings of the overhead cars: the full name and the part
    after «—» («Labo — Elyor» → also «Elyor»)."""
    out = set()
    for name in FinanceCar.objects.filter(is_overhead=True).values_list("name", flat=True):
        out.add(S._worker_key(name))
        if "—" in name:
            out.add(S._worker_key(name.split("—", 1)[1]))
    return out - {""}


def _is_car_op(worker: str, category_code: str, keys: set[str]) -> bool:
    # a salary to a driver who is also a car's name («Jumaka») is a salary, not the car
    return category_code != CAT_SALARY and S._worker_key(worker) in keys


def car_op_ids(refs) -> set[int]:
    """Company-car expenses typed with one of these order IDs (from FIN_OVERHEAD_SINCE):
    they are overhead, so the order does not count them (accounting.services.order_stats).
    A sborka sheet's own car money is the sheet's (payroll.car_money_op_ids), not this."""
    refs = [str(r) for r in refs if r]
    keys = _car_keys()
    if not refs or not keys:
        return set()
    rows = (
        Operation.objects.filter(
            is_deleted=False, kind=OpKind.EXPENSE, order_ref__in=refs, date__gte=since()
        )
        .exclude(category__code=CAT_SALARY)
        .values_list("id", "worker", "category__code")
    )
    return {i for i, w, c in rows if _is_car_op(w, c, keys)}


# ------------------------------------------------------------------ one month
def _company_ops(start: date, end: date):
    return Operation.objects.filter(
        is_deleted=False,
        date__gte=start,
        date__lte=end,
        category__excluded=False,
    ).exclude(category__kind=CategoryKind.INTERNAL)


def _boss_keys() -> set[str]:
    return {
        S._worker_key(n) for n in Worker.objects.filter(is_boss=True).values_list("name", flat=True)
    }


def _sheet_salaries(ym: str) -> tuple[Decimal, set[str], list[dict]]:
    """Approved salary sheets of `ym`: their overhead part (what is not on any ID), the
    names they cover, and one row per sheet. Used for EVERY month that has sheets —
    their ID part is already on the clients, so the wallet salaries of those people
    must not count again."""
    from payroll.models import CostSource, SalarySheet, SheetCost, SheetKind, SheetStatus
    from payroll.services import _sheet_keys

    first = date.fromisoformat(ym + "-01")
    sheets = list(
        SalarySheet.objects.filter(status=SheetStatus.APPROVED, month=first, snapshot__isnull=False)
        .select_related("worker")
        .prefetch_related("members__worker")
    )
    if not sheets:
        return ZERO, set(), []
    lines = dict(
        SheetCost.objects.filter(sheet__in=sheets, source=CostSource.LINE)
        .values("sheet_id")
        .annotate(t=Sum("amount"))
        .values_list("sheet_id", "t")
    )
    total, names, rows = ZERO, set(), []
    for sh in sheets:
        t = (sh.snapshot or {}).get("totals") or {}
        cost = D(t.get("earned_total")) - D(t.get("minus_total"))
        part = max(q2(cost - D(lines.get(sh.pk))), ZERO)
        total += part
        members = list(sh.members.all())  # prefetched — no query per sheet
        people = [m.worker for m in members] if sh.kind == SheetKind.SBORKA and members else [sh.worker]
        names |= _sheet_keys(sh, people)
        rows.append({"sheet": sh.number, "worker": sh.worker.name, "amount": part})
    return total, names, rows


def month_overhead(ym: str, memo: dict | None = None) -> dict:
    """{month, total, parts: [{key, label, amount}], sheets} — the month's overhead.
    `memo` ({ym: result}) is shared by one request so a month is worked out once."""
    if memo is not None and ym in memo:
        return memo[ym]
    from payroll.services import is_sheet_car_money, sheet_car_windows

    start, end = month_bounds(ym)
    new_rules = start >= since()
    car_keys = _car_keys() if new_rules else set()
    boss = _boss_keys()
    windows = sheet_car_windows()
    ops = list(
        _company_ops(start, end).values(
            "kind", "amount", "date", "order_ref", "worker", "pay_type", "category__code"
        )
    )
    general = cars = refunds = wallet_salary = ZERO
    sheet_total, covered, sheet_rows = _sheet_salaries(ym)
    # a salary paid in this month is mostly the last part of LAST month's sheet
    covered |= _sheet_salaries(add_months(ym, -1))[1]
    for o in ops:
        code, amt = o["category__code"], D(o["amount"])
        if o["kind"] == OpKind.INCOME:
            if code == CAT_REFUND and not o["order_ref"]:
                refunds += amt
            continue
        if code == CAT_SALARY:
            who = S._worker_key(o["worker"])
            if who in boss or o["pay_type"] == PayType.HOME:
                continue  # the boss: FIN_BOSS_SALARY stands for it
            if who not in covered:
                wallet_salary += amt
            continue
        if is_sheet_car_money(o["date"], o["worker"], code, windows):
            continue  # a sborka sheet's car money: the sheet put it on its IDs
        if car_keys and _is_car_op(o["worker"], code, car_keys):
            cars += amt
        elif not o["order_ref"]:
            general += amt
    boss_salary = q2(max(D(config.FIN_BOSS_SALARY or 0), ZERO))
    parts = [
        {"key": "general", "label": "ID'siz chiqimlar (ijara, kommunal, ofis …)", "amount": general},
        {"key": "refunds", "label": "(−) ID'siz qaytimlar", "amount": -refunds},
        {"key": "cars", "label": "Kompaniya mashinalari", "amount": cars},
        {"key": "sheets", "label": "Oylik varaqlari: fiksa / oklad", "amount": sheet_total},
        {
            "key": "wallet_salary",
            "label": "Hamyondan berilgan oyliklar (tasdiqlangan varag'i yo'qlar)",
            "amount": wallet_salary,
        },
        {"key": "boss", "label": "Rahbar oyligi (belgilangan)", "amount": boss_salary},
    ]
    parts = [{**p, "amount": q2(p["amount"])} for p in parts if p["amount"]]
    out = {
        "month": ym,
        "label": month_name(ym),
        "total": q2(sum((p["amount"] for p in parts), ZERO)),
        "parts": parts,
        "sheets": sheet_rows,
    }
    if memo is not None:
        memo[ym] = out
    return out


# ------------------------------------------------------------------ the rate
def _ready_refs(start: date, end: date) -> list[str]:
    """Orders that became Готов in [start, end]: site orders by «Bonuslar» (created on
    Готов), hand-made IDs by the day they were closed."""
    refs = list(
        OrderBonus.objects.filter(ready_date__gte=start, ready_date__lte=end).values_list(
            "order_ref", flat=True
        )
    )
    refs += list(
        ManualOrder.objects.filter(is_closed=True, closed__gte=start, closed__lte=end).values_list(
            "ref", flat=True
        )
    )
    return list(dict.fromkeys(refs))


def sales(start: date, end: date) -> Decimal:
    infos = S.order_infos(_ready_refs(start, end))
    return q2(sum((D(i.price_uzs) for i in infos.values()), ZERO))


def rate_for(ready: date, memo: dict | None = None) -> dict:
    """The rate for an order Готов on `ready`: the 3 whole months before its month."""
    ym = ym_of(ready)
    months = [add_months(ym, -k) for k in range(WINDOW_MONTHS, 0, -1)]
    w_start, _ = month_bounds(months[0])
    _, w_end = month_bounds(months[-1])
    overhead = q2(sum((month_overhead(m, memo)["total"] for m in months), ZERO))
    sold = sales(w_start, w_end)
    rate = (overhead / sold).quantize(Decimal("0.000001")) if sold > 0 and overhead > 0 else ZERO
    return {
        "months": months,
        "window_start": w_start,
        "window_end": w_end,
        "overhead": overhead,
        "sales": sold,
        "rate": rate,
    }


# ------------------------------------------------------------------ the shares
# Shares of a month are fixed only from this day of it on: by then last month's salary
# sheets are approved (the pay day is around the 10th), so the window is complete.
# Every order of one month gets the same rate (the first share of the month sets it).
SETTLE_DAY = 10


def _settled(ready: date) -> bool:
    t = today()
    return ym_of(ready) < ym_of(t) or t.day >= SETTLE_DAY


def _month_rate(ready: date, memo: dict) -> dict:
    """The month's rate: the one already used for a share of that month, else new."""
    key = ym_of(ready)
    if key in memo.setdefault("_rates", {}):
        return memo["_rates"][key]
    first, last = month_bounds(key)
    prev = (
        OrderOverhead.objects.filter(ready_date__gte=first, ready_date__lte=last)
        .order_by("created_at", "id")
        .first()
    )
    if prev is not None:
        r = {
            "rate": prev.rate,
            "window_start": prev.window_start,
            "window_end": prev.window_end,
            "overhead": prev.overhead_total,
            "sales": prev.sales_total,
        }
    else:
        r = rate_for(ready, memo)
    memo["_rates"][key] = r
    return r


def assign(ref: str, info=None, memo: dict | None = None) -> OrderOverhead | None:
    """Fix the share of one Готов order (from FIN_OVERHEAD_SINCE, once its month is
    settled). Idempotent: an existing share is returned as it is."""
    ref = str(ref)
    found = OrderOverhead.objects.filter(order_ref=ref).first()
    if found:
        return found
    info = info or S.order_info(ref)
    ready = getattr(info, "ready_date", None) if info else None
    if info is None or ready is None or ready < since() or not _settled(ready):
        return None
    r = _month_rate(ready, {} if memo is None else memo)
    base = q2(info.price_uzs)
    try:
        with transaction.atomic():
            return OrderOverhead.objects.create(
                order_ref=ref,
                ready_date=ready,
                base=base,
                rate=r["rate"],
                amount=q2(base * r["rate"]),
                window_start=r["window_start"],
                window_end=r["window_end"],
                overhead_total=r["overhead"],
                sales_total=r["sales"],
            )
    except IntegrityError:  # a parallel run wrote it first
        return OrderOverhead.objects.filter(order_ref=ref).first()


def assign_pending() -> int:
    """Every Готов order from FIN_OVERHEAD_SINCE without a share yet (Celery, hourly)."""
    done = set(OrderOverhead.objects.values_list("order_ref", flat=True))
    refs = [r for r in _ready_refs(since(), today()) if r not in done]
    if not refs:
        return 0
    infos = S.order_infos(refs)
    memo: dict = {}
    n = 0
    for ref in refs:
        if assign(ref, infos.get(ref), memo) is not None:
            n += 1
    return n


def shares(refs) -> dict[str, OrderOverhead]:
    refs = [str(r) for r in refs if r]
    return {o.order_ref: o for o in OrderOverhead.objects.filter(order_ref__in=refs)} if refs else {}


# ------------------------------------------------------------------ the report
def allocated(start: date, end: date) -> Decimal:
    return q2(
        OrderOverhead.objects.filter(ready_date__gte=start, ready_date__lte=end).aggregate(
            s=Sum("amount")
        )["s"]
        or ZERO
    )


def months_since() -> list[str]:
    """Months from FIN_OVERHEAD_SINCE up to and including the current one."""
    first, last = ym_of(since()), ym_of(today())
    out, ym = [], first
    while ym <= last:
        out.append(ym)
        ym = add_months(ym, 1)
    return out


def real_overhead(memo: dict | None = None) -> Decimal:
    """Every month's real overhead from the start up to today (this month in full)."""
    return q2(sum((month_overhead(m, memo)["total"] for m in months_since()), ZERO))


def boss_over_salary() -> Decimal:
    """Owner's rule: what the boss takes as his own salary («Oylik» / «Avans» / «Uy
    uchun» to the «Rahbar» worker) ABOVE the fixed FIN_BOSS_SALARY of that month is a
    profit withdrawal. Months from the start up to now."""
    keys = _boss_keys()
    if not keys:
        return ZERO
    fixed = max(D(config.FIN_BOSS_SALARY or 0), ZERO)
    per: dict[str, Decimal] = {}
    rows = Operation.objects.filter(
        is_deleted=False, kind=OpKind.EXPENSE, category__code=CAT_SALARY, date__gte=since()
    ).values_list("date", "worker", "amount")
    for d, who, amt in rows:
        if S._worker_key(who) in keys:
            per[ym_of(d)] = per.get(ym_of(d), ZERO) + D(amt)
    return q2(sum((max(v - fixed, ZERO) for v in per.values()), ZERO))


def withdrawn() -> Decimal:
    """«💰 Foyda yechish» rows + the boss's salary above his fixed one."""
    taken = D(
        Operation.objects.filter(
            is_deleted=False, kind=OpKind.EXPENSE, category__code=CAT_PROFIT
        ).aggregate(s=Sum("amount"))["s"]
    )
    return q2(taken + boss_over_salary())


def profit_pool(memo: dict | None = None) -> dict:
    """What may be taken out now — cash-safe: what the orders Готов from the start and
    paid in full brought over their direct cost, minus ALL the real overhead since the
    start (the shares are only how it is spread; an order not paid yet carries none of
    it here), minus what was already taken out."""
    rows = list(OrderOverhead.objects.all())
    refs = [o.order_ref for o in rows]
    infos = S.order_infos(refs)
    stats = S.order_stats_bulk(refs)
    paid_orders, waiting = [], []
    for o in rows:
        info = infos.get(o.order_ref)
        if info is None:
            continue
        spent = D((stats.get(o.order_ref) or {}).get("spent", ZERO))
        row = {
            "ref": o.order_ref,
            "client": info.client,
            "ready_date": o.ready_date,
            "price": q2(info.price_uzs),
            "spent": q2(spent),
            "gross": q2(D(info.price_uzs) - spent),
            "overhead": q2(o.amount),
            "net": q2(D(info.price_uzs) - spent - D(o.amount)),
        }
        full = info.manual.is_closed if info.manual else (info.rest is not None and info.rest <= 0)
        (paid_orders if full else waiting).append(row)
    gross = q2(sum((r["gross"] for r in paid_orders), ZERO))
    real = real_overhead(memo)
    out = withdrawn()
    return {
        "since": since(),
        "gross": gross,
        "overhead": real,
        "withdrawn": out,
        "available": q2(gross - real - out),
        "paid_orders": sorted(paid_orders, key=lambda r: r["ready_date"], reverse=True),
        "waiting": sorted(waiting, key=lambda r: r["ready_date"], reverse=True),
    }


def report(months: int = 6) -> dict:
    """The «Foyda» page: the rate now, every month's real overhead against the shares,
    and the profit that may be taken out."""
    memo: dict = {}
    cur = ym_of(today())
    rows = []
    for k in range(months, 0, -1):
        ym = add_months(cur, -k)
        m = dict(month_overhead(ym, memo))
        start, end = month_bounds(ym)
        share = allocated(start, end)
        m.update(
            allocated=share,
            difference=q2(m["total"] - share),
            sales=sales(start, end),
            counted=start >= since(),
        )
        rows.append(m)
    return {
        "rate": rate_for(today(), memo),
        "months": rows,
        "pool": profit_pool(memo),
        "since": since(),
    }


# ------------------------------------------------------------------ «Foyda yechish»
MAX_WITHDRAW = Decimal("10000000000000")


def withdraw_profit(member, amount, *, comment: str = "", site_user=None) -> Operation:
    """The boss takes profit out of a wallet: an expense in «💰 Foyda yechish»
    (excluded — not a company expense, not on any order). Refused above what the pool
    allows or the wallet holds. The only way this category is ever booked."""
    try:
        amount = q2(amount)
    except ArithmeticError as e:
        raise ServiceError("Summa noto'g'ri.", "amount") from e
    if not amount.is_finite() or amount <= 0 or amount > MAX_WITHDRAW:
        raise ServiceError("Summa noto'g'ri.", "amount")
    with transaction.atomic():
        # ONE withdrawal at a time, from any wallet: the category row is the lock
        FinanceCategory.objects.select_for_update().filter(code=CAT_PROFIT).first()
        pool = profit_pool()
        if amount > pool["available"]:
            raise ServiceError(
                f"Yechish mumkin bo'lgan foyda: {_som(pool['available'])}.", "amount"
            )
        have = S.balance(member)
        if amount > have:
            raise ServiceError(f"Hamyonda faqat {_som(have)} bor.", "amount")
        return S.create_operation(
            member=member,
            kind=OpKind.EXPENSE,
            amount=amount,
            category_code=CAT_PROFIT,
            comment=(comment or "Foyda yechish")[:2000],
            actor_admin=True,
            source="site",
            site_user=site_user,
            internal=True,
        )


__all__ = [
    "since",
    "car_op_ids",
    "month_overhead",
    "rate_for",
    "assign",
    "assign_pending",
    "shares",
    "report",
    "profit_pool",
    "withdraw_profit",
]
