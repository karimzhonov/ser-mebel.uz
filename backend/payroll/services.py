"""Oylik varaqlari — the rules (source of truth; the API only calls these).

The maths follow the office's Excel templates one to one:
  ODDIY    fiksa − kelmagan kunlar − kech qolgan (shtraf)
  SBORKA   Σ bajarilgan ishlar (so'm, by order ID), split between up to 3 people by
           share; «mashina puli» is listed apart and is NOT in the rest (as in Excel)
  OFIS     oklad + Σ olingan zakaz ($) × % × kurs − shtraf − kelmagan − ushlanmalar
  MENEJER  fiksa + olingan zakaz bonusi + topshirilgan zakaz bonusi − kelmagan (− shtraf)
  SOTUV /  fiksa + zakaz bonusi + pul yechish bonusi (by days, COLLECT_TIERS)
  ZAMER    + Instagram bonusi (INSTAGRAM_TIERS, $) − shtraf − kelmagan
and every sheet: − the advances (Avans) paid in the period → OSTATOK.

Advances are read live from «Amallar» (oylik, pay type «Avans») until the sheet is
approved; approval freezes everything into `snapshot`, renders the PDF and files it
into each worker's folder. Stage 1 books no money anywhere."""

from __future__ import annotations

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db import IntegrityError, transaction
from django.db.models import Max, Q
from django.utils import timezone

from accounting import salary as SAL
from accounting import services as S
from accounting import workers as WK
from accounting.constants import BONUS_TIERS, PayType
from accounting.models import Worker, WorkerFile
from accounting.text import add_months, month_full, today
from core.exceptions import ServiceError

from .models import LineSection, SalarySheet, SheetKind, SheetLine, SheetMember, SheetStatus

ZERO = Decimal(0)
HUNDRED = Decimal(100)
MAX_PERIOD_DAYS = 400
MAX_LINES = 200
MAX_MEMBERS = 3

# «Pul yechish bonusi»: days from hand-over to the money collected → percent (the
# templates' Sozlamalar: 0–3 kun 0,5 %, 4–7 kun 0,4 %, 8–30 kun 0,3 %, later 0).
COLLECT_TIERS = [(int(d), Decimal(str(p))) for d, p in BONUS_TIERS]
# «Instagram istoriya bonusi» ($): from N stories on → bonus
INSTAGRAM_TIERS = [(0, ZERO), (20, Decimal(50)), (30, Decimal(75)), (40, Decimal(100))]

# which parts each kind uses (anything else on the sheet is ignored and hidden)
KIND_SECTIONS: dict[str, tuple[str, ...]] = {
    SheetKind.ODDIY: (),
    SheetKind.SBORKA: (LineSection.JOB, LineSection.CAR),
    SheetKind.OFIS: (LineSection.TAKEN, LineSection.DEDUCTION),
    SheetKind.MENEJER: (LineSection.TAKEN, LineSection.DELIVERED),
    SheetKind.SOTUV: (LineSection.TAKEN, LineSection.COLLECT),
    SheetKind.ZAMER: (LineSection.TAKEN, LineSection.COLLECT),
}
KIND_FIELDS: dict[str, tuple[str, ...]] = {
    SheetKind.ODDIY: ("fixed", "late", "absent"),
    SheetKind.SBORKA: (),
    SheetKind.OFIS: ("fixed", "bonus", "late", "absent"),
    SheetKind.MENEJER: ("fixed", "bonus", "bonus2", "late", "absent"),
    SheetKind.SOTUV: ("fixed", "bonus", "instagram", "late", "absent"),
    SheetKind.ZAMER: ("fixed", "bonus", "instagram", "late", "absent"),
}
REF_SECTIONS = {LineSection.JOB, LineSection.TAKEN, LineSection.DELIVERED, LineSection.COLLECT}
USD_SECTIONS = {LineSection.TAKEN, LineSection.DELIVERED}  # amounts typed in $
SECTION_TITLES = {
    LineSection.JOB: "Bajarilgan ishlar / buyurtmalar",
    LineSection.TAKEN: "Olingan zakazlar bonusi",
    LineSection.DELIVERED: "Topshirilgan zakazlar bonusi",
    LineSection.COLLECT: "Pul yechish bonusi",
    LineSection.DEDUCTION: "Ushlanmalar (beydjik va b.)",
    LineSection.CAR: "Mashina puli (alohida, qoldiqqa kirmaydi)",
}

# plain strings everywhere: rows come from the DB / JSON as "job", never as the enum
def _v(x) -> str:
    return getattr(x, "value", x)


KIND_SECTIONS = {_v(k): tuple(_v(x) for x in v) for k, v in KIND_SECTIONS.items()}
KIND_FIELDS = {_v(k): v for k, v in KIND_FIELDS.items()}
REF_SECTIONS = {_v(x) for x in REF_SECTIONS}
USD_SECTIONS = {_v(x) for x in USD_SECTIONS}
SECTION_TITLES = {_v(k): v for k, v in SECTION_TITLES.items()}

HEADER_FIELDS = (
    "kind",
    "section",
    "position",
    "period_start",
    "period_end",
    "usd_rate",
    "fixed",
    "bonus_percent",
    "bonus2_percent",
    "late_days",
    "late_rate",
    "late_dates",
    "absent_days",
    "absent_rate",
    "absent_dates",
    "instagram_count",
    "note",
)


# ------------------------------------------------------------------ small helpers
def D(v) -> Decimal:
    if v is None or v == "":
        return ZERO
    try:
        return Decimal(str(v))
    except Exception as e:  # noqa: BLE001 — anything not a number
        raise ServiceError("Raqam noto'g'ri.") from e


def q2(v) -> Decimal:
    return D(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def plain(v) -> str:
    """A percent / share as typed: 100 → «100», 1.2000 → «1.2» (never «1E+2»)."""
    out = f"{D(v).normalize():f}"
    return out


def ym_of(d: date) -> str:
    return d.strftime("%Y-%m")


def _norm_ref(ref) -> str:
    return str(ref or "").strip().lstrip("#")[:32]


def collect_percent(days: int | None) -> Decimal | None:
    if days is None:
        return None
    if days < 0:
        return ZERO
    for limit, pct in COLLECT_TIERS:
        if days <= limit:
            return pct
    return ZERO


def instagram_usd(count: int) -> Decimal:
    out = ZERO
    for start, usd in INSTAGRAM_TIERS:
        if count >= start:
            out = usd
    return out


def members_of(sheet: SalarySheet) -> list[SheetMember]:
    """SBORKA people with their shares; any other kind — the worker alone, 100 %."""
    rows = list(sheet.members.select_related("worker"))
    if sheet.kind == SheetKind.SBORKA and rows:
        return rows
    return [SheetMember(sheet=sheet, worker=sheet.worker, share=HUNDRED, position=0)]


# ------------------------------------------------------------------ advances
def advances_for(workers: list[Worker], start: date, end: date) -> list:
    """«Avans» payments to these people in the period, oldest first."""
    keys = {S._worker_key(w.name): w for w in workers}
    rows = [
        t
        for t in S.salary_ops(start, end).filter(pay_type=PayType.ADVANCE)
        if S._worker_key(t.worker) in keys
    ]
    rows.sort(key=lambda t: (t.date, t.number))
    return rows


def _advance_row(t, workers_by_key: dict) -> dict:
    w = workers_by_key.get(S._worker_key(t.worker))
    usd = t.currency == "USD" and t.orig_amount is not None
    return {
        "id": t.id,
        "number": t.number,
        "date": t.date.isoformat(),
        "worker_id": w.pk if w else None,
        "worker": w.name if w else t.worker,
        "amount": str(q2(t.amount)),
        "currency": "USD" if usd else "UZS",
        "orig_amount": str(t.orig_amount) if usd else None,
        "rate": str(t.rate) if usd and t.rate else None,
        "given_by": t.member.name,
        "comment": t.comment or "",
    }


# ------------------------------------------------------------------ the maths
def _line_value(sheet: SalarySheet, ln: SheetLine) -> dict:
    """One row with what it adds to the sheet in so'm (`value`)."""
    rate = sheet.usd_rate
    amount = D(ln.amount)
    row = {
        "id": ln.pk,
        "section": ln.section,
        "order_ref": ln.order_ref,
        "order_id": ln.order_id,
        "title": ln.title,
        "on_date": ln.on_date.isoformat() if ln.on_date else None,
        "paid_on": ln.paid_on.isoformat() if ln.paid_on else None,
        "currency": ln.currency,
        "amount": str(q2(amount)),
        "rate": str(ln.rate) if ln.rate is not None else None,
        "days": None,
        "percent": None,
        "bonus_usd": None,
        "value": "0",
    }
    if ln.section in (LineSection.JOB, LineSection.CAR):
        value = amount
    elif ln.section in USD_SECTIONS:
        pct = D(sheet.bonus_percent if ln.section == LineSection.TAKEN else sheet.bonus2_percent)
        bonus = amount * pct / HUNDRED
        row["percent"] = plain(pct)
        row["bonus_usd"] = str(q2(bonus))
        value = bonus * rate
    elif ln.section == LineSection.COLLECT:
        days = (ln.paid_on - ln.on_date).days if ln.on_date and ln.paid_on else None
        pct = collect_percent(days)
        row["days"], row["percent"] = days, None if pct is None else plain(pct)
        mult = Decimal(1) if ln.currency == "UZS" else rate
        value = amount * mult * (pct or ZERO) / HUNDRED
    elif ln.section == LineSection.DEDUCTION:
        value = amount if ln.currency == "UZS" else amount * (ln.rate or rate)
    else:  # pragma: no cover — guarded by the choices
        value = ZERO
    row["value"] = str(q2(value))
    return row


def compute(sheet: SalarySheet) -> dict:
    """The whole sheet as data (the API, the page and the PDF all read this)."""
    kind = sheet.kind
    fields = KIND_FIELDS[kind]
    sections = KIND_SECTIONS[kind]
    lines = [ln for ln in sheet.lines.all() if ln.section in sections]
    rows = [_line_value(sheet, ln) for ln in lines]
    by_sec: dict[str, list[dict]] = {s: [] for s in sections}
    for r in rows:
        by_sec[r["section"]].append(r)

    def total(sec) -> Decimal:
        return sum((D(r["value"]) for r in by_sec.get(sec, [])), ZERO)

    rate = D(sheet.usd_rate)
    earned: list[tuple[str, Decimal]] = []
    minus: list[tuple[str, Decimal]] = []
    if "fixed" in fields:
        earned.append(("Oklad" if kind == SheetKind.OFIS else "Fiksa (oylik maosh)", q2(sheet.fixed)))
    if kind == SheetKind.SBORKA:
        earned.append(("Jami buyurtmalar summasi", q2(total(LineSection.JOB))))
    if "bonus" in fields:
        earned.append(
            (
                "Olingan zakazlar bonusi" if kind == SheetKind.MENEJER else "Buyurtma bonusi",
                q2(total(LineSection.TAKEN)),
            )
        )
    if "bonus2" in fields:
        earned.append(("Topshirilgan zakazlar bonusi", q2(total(LineSection.DELIVERED))))
    if LineSection.COLLECT in sections:
        earned.append(("Pul yechish bonusi", q2(total(LineSection.COLLECT))))
    insta_usd = ZERO
    if "instagram" in fields:
        insta_usd = instagram_usd(int(sheet.instagram_count or 0))
        earned.append(("Instagram bonusi", q2(insta_usd * rate)))
    if "late" in fields:
        minus.append(("Kech qolgan (shtraf)", q2(D(sheet.late_days) * D(sheet.late_rate))))
    if "absent" in fields:
        minus.append(("Kelmagan kunlar", q2(D(sheet.absent_days) * D(sheet.absent_rate))))
    if LineSection.DEDUCTION in sections:
        minus.append(("Ushlanmalar", q2(total(LineSection.DEDUCTION))))

    people = members_of(sheet)
    workers = [m.worker for m in people]
    by_key = {S._worker_key(w.name): w for w in workers}
    if sheet.snapshot is None:
        adv_rows = [_advance_row(t, by_key) for t in advances_for(workers, sheet.period_start, sheet.period_end)]
    else:  # frozen: never re-read the wallets
        adv_rows = sheet.snapshot.get("advances", [])
    adv_total = q2(sum((D(a["amount"]) for a in adv_rows), ZERO))

    earned_total = q2(sum((v for _, v in earned), ZERO))
    minus_total = q2(sum((v for _, v in minus), ZERO))
    rest = q2(earned_total - minus_total - adv_total)

    member_rows = []
    if kind == SheetKind.SBORKA:
        job_total = total(LineSection.JOB)
        for m in people:
            share_amount = q2(job_total * D(m.share) / HUNDRED)
            own = q2(sum((D(a["amount"]) for a in adv_rows if a["worker_id"] == m.worker_id), ZERO))
            member_rows.append(
                {
                    "worker_id": m.worker_id,
                    "name": m.worker.name,
                    "share": plain(m.share),
                    "amount": str(share_amount),
                    "advances": str(own),
                    "rest": str(q2(share_amount - own)),
                }
            )
    return {
        "lines": rows,
        "sections": [
            {"key": s, "title": SECTION_TITLES[s], "total": str(q2(total(s)))} for s in sections
        ],
        "advances": adv_rows,
        "members": member_rows,
        "totals": {
            "earned": [{"label": k, "amount": str(v)} for k, v in earned],
            "minus": [{"label": k, "amount": str(v)} for k, v in minus],
            "earned_total": str(earned_total),
            "minus_total": str(minus_total),
            "advances_total": str(adv_total),
            "rest": str(rest),
            "rest_usd": str(q2(rest / rate)) if rate > 0 else None,
            "car_total": str(q2(total(LineSection.CAR))) if LineSection.CAR in sections else None,
            "instagram_usd": str(insta_usd) if "instagram" in fields else None,
        },
    }


def warnings(sheet: SalarySheet) -> list[str]:
    """Things the boss should look at before approving (nothing here blocks)."""
    out: list[str] = []
    seen: dict[tuple[str, str], int] = {}
    for ln in sheet.lines.all():
        if ln.section in KIND_SECTIONS[sheet.kind] and ln.order_ref:
            k = (ln.section, ln.order_ref)
            seen[k] = seen.get(k, 0) + 1
    for (sec, ref), n in seen.items():
        if n > 1:
            out.append(f"ID {ref} «{SECTION_TITLES[sec]}» bo'limida {n} marta yozilgan.")
    refs = {ref for _, ref in seen}
    if refs:
        others = (
            SheetLine.objects.filter(order_ref__in=refs, section__in=[s for s, _ in seen])
            .exclude(sheet=sheet)
            .filter(
                sheet__period_start__lte=sheet.period_end, sheet__period_end__gte=sheet.period_start
            )
            .select_related("sheet__worker")
        )
        for ln in others:
            if (ln.section, ln.order_ref) in seen:
                out.append(
                    f"ID {ln.order_ref} shu davrdagi boshqa varaqda ham bor: "
                    f"№{ln.sheet.number} ({ln.sheet.worker.name})."
                )
    if sheet.kind == SheetKind.SBORKA and sheet.snapshot is None:
        names = [m.worker.name for m in members_of(sheet)]
        if len(names) > 1:
            out.append(
                "Sheriklar avanslari ham shu varaqqa qo'shildi: " + ", ".join(names) + "."
            )
    if sheet.snapshot is None:
        untyped = SAL.untyped(sheet.worker, sheet.period_start, sheet.period_end)
        if untyped:
            out.append(
                f"Turi (Avans / Oylik) yozilmagan {len(untyped)} ta to'lov bor — varaqqa "
                "qo'shilmadi, «Amallar»da tekshiring."
            )
    return out


def refresh_totals(sheet: SalarySheet) -> SalarySheet:
    t = compute(sheet)["totals"]
    sheet.totals = {k: t[k] for k in ("earned_total", "minus_total", "advances_total", "rest")}
    sheet.save(update_fields=["totals", "updated_at"])
    return sheet


# ------------------------------------------------------------------ create / edit
def _check_period(start: date, end: date) -> None:
    if start > end:
        raise ServiceError("Davr boshi oxiridan keyin bo'lmasin.", "period_start")
    if (end - start).days > MAX_PERIOD_DAYS:
        raise ServiceError("Davr juda uzun (ko'pi bilan bir yil).", "period_end")


def _check_month(worker: Worker, month: date) -> None:
    """Same rule as the folder: no sheet for a month after the next salary month."""
    last = max(date.fromisoformat(SAL.next_month(worker) + "-01"), today().replace(day=1))
    if month > last:
        raise ServiceError("Kelgusi oy uchun oylik varaqasi ochib bo'lmaydi.", "month")


def _next_number() -> int:
    return (SalarySheet.objects.aggregate(m=Max("number"))["m"] or 0) + 1


def create_sheet(worker: Worker, *, month: str | None = None, kind: str | None = None, by=None) -> SalarySheet:
    """A new draft. Kind, fiksa, percents, rates and SBORKA partners are copied from the
    worker's previous sheet; the period follows the pay day (accounting/salary.py)."""
    if not worker.is_active:
        raise ServiceError("Bu xodim faol emas.", "worker")
    ym = month or SAL.next_month(worker)
    if not re.fullmatch(r"\d{4}-\d{2}", ym):
        raise ServiceError("Oy noto'g'ri (YYYY-MM).", "month")
    first = date.fromisoformat(ym + "-01")
    _check_month(worker, first)
    dup = SalarySheet.objects.filter(worker=worker, month=first).first()
    if dup:
        raise ServiceError(
            f"{worker.name} uchun {month_full(ym)} varag'i bor: №{dup.number}.", "month"
        )
    prev = worker.salary_sheets.order_by("-month", "-number").first()
    kind = kind or (prev.kind if prev else "")
    if kind not in SheetKind.values:
        raise ServiceError("Varaq turini tanlang.", "kind")
    start, end = SAL.period(worker, ym)
    rate = S.usd_rate()
    if not rate or rate <= 0:
        raise ServiceError("Dollar kursi topilmadi — Moliya sozlamalarida kiriting.")
    same = prev if prev and prev.kind == kind else None
    copy = {
        f: getattr(same, f)
        for f in ("fixed", "bonus_percent", "bonus2_percent", "late_rate", "absent_rate")
    } if same else {}
    for _ in range(5):
        try:
            with transaction.atomic():
                sheet = SalarySheet.objects.create(
                    number=_next_number(),
                    kind=kind,
                    worker=worker,
                    section=(same.section if same else "") or worker.group,
                    position=(same.position if same else "") or worker.position,
                    month=first,
                    period_start=start,
                    period_end=end,
                    usd_rate=rate,
                    created_by=by,
                    updated_by=by,
                    **copy,
                )
                if kind == SheetKind.SBORKA:
                    old = list(same.members.all()) if same else []
                    if old:
                        for i, m in enumerate(old):
                            SheetMember.objects.create(
                                sheet=sheet, worker_id=m.worker_id, share=m.share, position=i
                            )
                    else:
                        SheetMember.objects.create(sheet=sheet, worker=worker, share=HUNDRED)
            break
        except IntegrityError:
            continue
    else:
        raise ServiceError("Varaqni ochib bo'lmadi, qayta urinib ko'ring.")
    return refresh_totals(sheet)


def _lock(sheet: SalarySheet) -> SalarySheet:
    return SalarySheet.objects.select_for_update().get(pk=sheet.pk)


def _clean_members(sheet: SalarySheet, kind: str, raw) -> list[dict] | None:
    if kind != SheetKind.SBORKA:
        return []
    if raw is None:
        return None  # keep as they are
    rows, seen = [], set()
    for i, m in enumerate(raw):
        wid = m.get("worker")
        w = Worker.objects.filter(pk=wid).first() if wid else None
        if w is None:
            raise ServiceError("Sherikni ro'yxatdan tanlang.", "members")
        if w.pk in seen:
            raise ServiceError(f"{w.name} ikki marta tanlangan.", "members")
        seen.add(w.pk)
        share = D(m.get("share"))
        if share <= 0 or share > HUNDRED:
            raise ServiceError("Ulush 0 dan katta va 100 % gacha bo'lsin.", "members")
        rows.append({"worker": w, "share": share, "position": i})
    if not rows or rows[0]["worker"].pk != sheet.worker_id:
        raise ServiceError("Birinchi qatorda varaq egasi turishi kerak.", "members")
    if len(rows) > MAX_MEMBERS:
        raise ServiceError("Ko'pi bilan 3 kishi (xodim + 2 sherik).", "members")
    if sum((r["share"] for r in rows), ZERO) != HUNDRED:
        raise ServiceError("Ulushlar yig'indisi 100 % bo'lishi kerak.", "members")
    return rows


def _clean_lines(kind: str, raw) -> list[dict] | None:
    if raw is None:
        return None
    if len(raw) > MAX_LINES:
        raise ServiceError(f"Qatorlar juda ko'p ({MAX_LINES} tagacha).", "lines")
    allowed = KIND_SECTIONS[kind]
    out = []
    refs = set()
    for i, ln in enumerate(raw, start=1):
        sec = ln.get("section")
        if sec not in allowed:
            raise ServiceError(f"{i}-qator: bu varaq turida «{sec}» bo'limi yo'q.", "lines")
        amount = D(ln.get("amount"))
        if amount <= 0:
            raise ServiceError(f"{i}-qator: summa 0 dan katta bo'lsin.", "lines")
        cur = ln.get("currency") or ("USD" if sec in USD_SECTIONS else "UZS")
        if sec in (LineSection.JOB, LineSection.CAR):
            cur = "UZS"
        if sec in USD_SECTIONS:
            cur = "USD"
        if cur not in ("UZS", "USD"):
            raise ServiceError(f"{i}-qator: valyuta UZS yoki USD.", "lines")
        ref = _norm_ref(ln.get("order_ref"))
        if sec in REF_SECTIONS:
            if not ref:
                raise ServiceError(f"{i}-qator: buyurtma ID ni yozing.", "lines")
            refs.add(ref)
        rate = ln.get("rate")
        rate = D(rate) if rate not in (None, "") else None
        if rate is not None and rate <= 0:
            raise ServiceError(f"{i}-qator: kurs 0 dan katta bo'lsin.", "lines")
        on_date, paid_on = ln.get("on_date"), ln.get("paid_on")
        if sec == LineSection.COLLECT and on_date and paid_on and paid_on < on_date:
            raise ServiceError(
                f"{i}-qator: pul yechilgan sana topshirilgan sanadan oldin bo'lmasin.", "lines"
            )
        out.append(
            {
                "section": sec,
                "position": i,
                "order_ref": ref,
                "title": str(ln.get("title") or "").strip()[:255],
                "on_date": on_date if sec in (LineSection.COLLECT, LineSection.DEDUCTION) else None,
                "paid_on": paid_on if sec == LineSection.COLLECT else None,
                "currency": cur,
                "amount": q2(amount),
                "rate": rate if sec == LineSection.DEDUCTION and cur == "USD" else None,
            }
        )
    infos = S.order_infos(refs) if refs else {}
    missing = sorted(refs - set(infos))
    if missing:
        raise ServiceError("Bunday buyurtma ID topilmadi: " + ", ".join(missing), "lines")
    for r in out:
        info = infos.get(r["order_ref"]) if r["order_ref"] else None
        r["order"] = info.order if info else None
        if info and not r["title"]:
            r["title"] = info.client[:255]
    return out


def update_sheet(sheet: SalarySheet, data: dict, *, by=None) -> SalarySheet:
    """Header fields + (optionally) the whole members / lines lists. Drafts only."""
    with transaction.atomic():
        sheet = _lock(sheet)
        if sheet.status != SheetStatus.DRAFT:
            raise ServiceError("Faqat qoralamani o'zgartirish mumkin — avval qaytaring.")
        kind = data.get("kind", sheet.kind)
        if kind not in SheetKind.values:
            raise ServiceError("Varaq turini tanlang.", "kind")
        for f in HEADER_FIELDS:
            if f in data and f != "kind":
                setattr(sheet, f, data[f])
        sheet.kind = kind
        if "month" in data:
            ym = str(data["month"] or "")
            if not re.fullmatch(r"\d{4}-\d{2}", ym):
                raise ServiceError("Oy noto'g'ri (YYYY-MM).", "month")
            first = date.fromisoformat(ym + "-01")
            _check_month(sheet.worker, first)
            dup = (
                SalarySheet.objects.filter(worker=sheet.worker, month=first)
                .exclude(pk=sheet.pk)
                .first()
            )
            if dup:
                raise ServiceError(f"Bu oy uchun varaq bor: №{dup.number}.", "month")
            sheet.month = first
        _check_period(sheet.period_start, sheet.period_end)
        if D(sheet.usd_rate) <= 0:
            raise ServiceError("USD kursi 0 dan katta bo'lsin.", "usd_rate")
        for f in ("fixed", "late_rate", "absent_rate", "bonus_percent", "bonus2_percent"):
            if D(getattr(sheet, f)) < 0:
                raise ServiceError("Manfiy son yozib bo'lmaydi.", f)
        for f in ("bonus_percent", "bonus2_percent"):
            if D(getattr(sheet, f)) > HUNDRED:
                raise ServiceError("Foiz 100 dan oshmasin.", f)
        members = _clean_members(sheet, kind, data.get("members"))
        lines = _clean_lines(kind, data.get("lines"))
        sheet.updated_by = by
        sheet.save()
        if members is not None:
            sheet.members.all().delete()
            for m in members:
                SheetMember.objects.create(sheet=sheet, **m)
            if kind == SheetKind.SBORKA and not members:
                SheetMember.objects.create(sheet=sheet, worker=sheet.worker, share=HUNDRED)
        elif kind == SheetKind.SBORKA and not sheet.members.exists():
            SheetMember.objects.create(sheet=sheet, worker=sheet.worker, share=HUNDRED)
        if lines is not None:
            sheet.lines.all().delete()
            SheetLine.objects.bulk_create([SheetLine(sheet=sheet, **r) for r in lines])
    return refresh_totals(sheet)


def delete_sheet(sheet: SalarySheet) -> None:
    with transaction.atomic():
        sheet = _lock(sheet)
        if sheet.status != SheetStatus.DRAFT or sheet.version:
            raise ServiceError(
                "Tasdiqlangan (yoki avval tasdiqlangan) varaqni o'chirib bo'lmaydi."
            )
        sheet.delete()


# ------------------------------------------------------------------ the flow
def _ready(sheet: SalarySheet) -> None:
    """Nothing to pay at all is a mistake, not a sheet."""
    if sheet.kind == SheetKind.SBORKA:
        if not sheet.lines.filter(section=LineSection.JOB).exists():
            raise ServiceError("Bajarilgan ishlar ro'yxati bo'sh.")
    elif D(sheet.fixed) <= 0 and not sheet.lines.filter(
        section__in=KIND_SECTIONS[sheet.kind]
    ).exists():
        raise ServiceError("Fiksa yozilmagan va bonus qatorlari yo'q.")


def submit_sheet(sheet: SalarySheet, *, by=None) -> SalarySheet:
    """Bugalter: «Tasdiqlashga yuborish»."""
    with transaction.atomic():
        sheet = _lock(sheet)
        if sheet.status != SheetStatus.DRAFT:
            raise ServiceError("Varaq allaqachon yuborilgan.")
        _ready(sheet)
        sheet.status = SheetStatus.SUBMITTED
        sheet.submitted_by, sheet.submitted_at = by, timezone.now()
        sheet.returned_note = ""
        sheet.save()
    return refresh_totals(sheet)


def return_sheet(sheet: SalarySheet, *, reason: str = "", by=None) -> SalarySheet:
    """Back to a draft: the boss returns it (also an approved one) with a reason, or the
    accountant takes a submitted one back. The PDFs already filed stay in the folders."""
    with transaction.atomic():
        sheet = _lock(sheet)
        if sheet.status == SheetStatus.DRAFT:
            raise ServiceError("Varaq allaqachon qoralama.")
        sheet.status = SheetStatus.DRAFT
        sheet.snapshot = None
        sheet.returned_note = str(reason or "").strip()[:500]
        sheet.updated_by = by
        sheet.save()
    return refresh_totals(sheet)


def _slug(s: str) -> str:
    return re.sub(r"[^\w-]+", "_", s, flags=re.U).strip("_")[:60] or "xodim"


def approve_sheet(sheet: SalarySheet, *, by=None) -> SalarySheet:
    """Rahbar: «Tasdiqlash». Freezes the sheet, renders the PDF and files it into the
    folder of each worker on it (SBORKA: every partner too)."""
    from .pdf import render_pdf

    with transaction.atomic():
        sheet = _lock(sheet)
        if sheet.status == SheetStatus.APPROVED:
            raise ServiceError("Varaq allaqachon tasdiqlangan.")
        _ready(sheet)
        view = sheet_view(sheet)
        sheet.status = SheetStatus.APPROVED
        sheet.approved_by, sheet.approved_at = by, timezone.now()
        sheet.version += 1
        sheet.returned_note = ""
        view.update(
            status=sheet.status,
            status_label=sheet.get_status_display(),
            version=sheet.version,
            approved_by=getattr(by, "name", "") or "",
            approved_at=sheet.approved_at.isoformat(),
        )
        sheet.snapshot = view
        sheet.totals = {
            k: view["totals"][k] for k in ("earned_total", "minus_total", "advances_total", "rest")
        }
        sheet.save()
        content = render_pdf(view)
        ym = ym_of(sheet.month)
        suffix = f"_v{sheet.version}" if sheet.version > 1 else ""
        who = getattr(by, "name", "") or "rahbar"
        for m in members_of(sheet):
            WK.save_file(
                m.worker,
                kind=WorkerFile.Kind.SALARY,
                name=f"Oylik_{ym}_{_slug(m.worker.name)}_No{sheet.number}{suffix}.pdf",
                content=content,
                month=sheet.month,
                comment=f"Saytdagi oylik varaqasi №{sheet.number} (tasdiqladi: {who})",
                user=by,
            )
    return sheet


# ------------------------------------------------------------------ read
def sheet_view(sheet: SalarySheet) -> dict:
    """Everything the page and the PDF show. An approved sheet is its snapshot."""
    if sheet.status == SheetStatus.APPROVED and sheet.snapshot:
        return dict(sheet.snapshot)
    c = compute(sheet)
    ym = ym_of(sheet.month)
    return {
        "id": sheet.pk,
        "number": sheet.number,
        "kind": sheet.kind,
        "kind_label": sheet.get_kind_display(),
        "worker_id": sheet.worker_id,
        "worker": sheet.worker.name,
        "section": sheet.section,
        "position": sheet.position,
        "month": ym,
        "month_label": month_full(ym),
        "period_start": sheet.period_start.isoformat(),
        "period_end": sheet.period_end.isoformat(),
        "pay_date": SAL.pay_date(sheet.worker, ym).isoformat(),
        "usd_rate": str(sheet.usd_rate),
        "fixed": str(q2(sheet.fixed)),
        "bonus_percent": plain(sheet.bonus_percent),
        "bonus2_percent": plain(sheet.bonus2_percent),
        "late_days": sheet.late_days,
        "late_rate": str(q2(sheet.late_rate)),
        "late_dates": sheet.late_dates,
        "absent_days": sheet.absent_days,
        "absent_rate": str(q2(sheet.absent_rate)),
        "absent_dates": sheet.absent_dates,
        "instagram_count": sheet.instagram_count,
        "note": sheet.note,
        "fields": list(KIND_FIELDS[sheet.kind]),
        "status": sheet.status,
        "status_label": sheet.get_status_display(),
        "version": sheet.version,
        **c,
    }


def sheets_qs():
    return SalarySheet.objects.select_related(
        "worker", "created_by", "submitted_by", "approved_by", "updated_by"
    )


def filter_sheets(qs, *, status: str = "", month: str = "", worker: str = "", search: str = ""):
    if status:
        qs = qs.filter(status__in=status.split(","))
    if month and re.fullmatch(r"\d{4}-\d{2}", month):
        qs = qs.filter(month=date.fromisoformat(month + "-01"))
    if worker and str(worker).isdigit():
        qs = qs.filter(Q(worker_id=int(worker)) | Q(members__worker_id=int(worker))).distinct()
    if search:
        qs = qs.filter(
            Q(worker__name__icontains=search)
            | Q(members__worker__name__icontains=search)
            | Q(lines__order_ref=search.strip().lstrip("#"))
        ).distinct()
    return qs


def options() -> dict:
    return {
        "kinds": [
            {
                "value": k.value,
                "label": k.label,
                "sections": list(KIND_SECTIONS[k.value]),
                "fields": list(KIND_FIELDS[k.value]),
            }
            for k in SheetKind
        ],
        "section_titles": SECTION_TITLES,
        "workers": [
            {"id": w.pk, "name": w.name, "group": w.group, "position": w.position}
            for w in Worker.objects.filter(is_active=True).defer("salary_template")
        ],
        "collect_tiers": [{"days": d, "percent": str(p)} for d, p in COLLECT_TIERS],
        "instagram_tiers": [{"from": n, "usd": str(u)} for n, u in INSTAGRAM_TIERS],
        "this_month": today().strftime("%Y-%m"),
        "next_month": add_months(today().strftime("%Y-%m"), 1),
    }
