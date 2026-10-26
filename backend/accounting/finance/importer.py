"""Import of the old Google Sheets finance book (code.txt) into the DB.

Sources: a downloaded .xlsx (File → Download → Microsoft Excel) or the Google Sheets
API with a service account. Re-running is safe: every table has a natural key (see
docs/FINANCE_MIGRATION.md) and rows are updated, not duplicated. Operations that were
created in the new bot/site (source != "import") are never overwritten — a number
clash is reported instead.

The «Davomat» sheet (HR, phase 2) is never read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from constance import config
from django.db import transaction

from oauth.models import TelegramMember, TelegramRole

from .. import services as S
from ..finance_constants import CategoryKind
from ..finance_models import (
    ClientFeedback,
    FinanceCategory,
    ManualOrder,
    MonthReport,
    Operation,
    OrderBonus,
    SiteEntryTask,
    WarrantyLetter,
    Worker,
)

SHEETS = [
    "Xodimlar",
    "Sozlamalar",
    "Ishchilar",
    "Buyurtmalar",
    "Amallar",
    "Oylik hisob",
    "Bonuslar",
    "Kafolat xatlari",
    "Saytga kiritish",
    "Mijoz fikrlari",
]
ROLE_MAP = {
    "admin": TelegramRole.ADMIN,
    "xodim": TelegramRole.STAFF,
    "pending": TelegramRole.PENDING,
    "blocked": TelegramRole.BLOCKED,
}
EPOCH = date(1899, 12, 30)  # Google/Excel serial dates


# ------------------------------------------------------------------ readers
class XlsxSource:
    def __init__(self, path: str):
        from openpyxl import load_workbook

        self.values = load_workbook(path, data_only=True, read_only=True)
        self.formulas = load_workbook(path, data_only=False, read_only=True)

    def rows(self, sheet: str, formulas=False) -> list[dict] | None:
        wb = self.formulas if formulas else self.values
        if sheet not in wb.sheetnames:
            return None
        it = wb[sheet].iter_rows(values_only=True)
        head = next(it, None)
        if not head:
            return []
        keys = [str(h).strip() if h is not None else "" for h in head]
        out = []
        for r in it:
            if r is None or all(v in (None, "") for v in r):
                continue
            out.append({k: v for k, v in zip(keys, r) if k})
        return out


class GoogleSource:
    """Sheets API v4 with a service-account JSON (share the sheet with its e-mail)."""

    def __init__(self, sheet_id: str, credentials_file: str):
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_file(
            credentials_file, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
        )
        self.session = AuthorizedSession(creds)
        self.base = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}"
        meta = self.session.get(self.base, params={"fields": "sheets.properties.title"}, timeout=60)
        meta.raise_for_status()
        self.titles = {s["properties"]["title"] for s in meta.json()["sheets"]}

    def rows(self, sheet: str, formulas=False) -> list[dict] | None:
        if sheet not in self.titles:
            return None
        r = self.session.get(
            f"{self.base}/values/{sheet}",
            params={
                "valueRenderOption": "FORMULA" if formulas else "UNFORMATTED_VALUE",
                "dateTimeRenderOption": "SERIAL_NUMBER",
            },
            timeout=120,
        )
        r.raise_for_status()
        vals = r.json().get("values", [])
        if not vals:
            return []
        keys = [str(h).strip() for h in vals[0]]
        return [
            {k: v for k, v in zip(keys, row) if k}
            for row in vals[1:]
            if any(str(v).strip() for v in row)
        ]


# ------------------------------------------------------------------ cell helpers
def s(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip().lstrip("'")


def dec(v) -> Decimal | None:
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v).replace(" ", "").replace(" ", "").replace(",", "."))
    except InvalidOperation:
        return None


def to_date(v) -> date | None:
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)):
        return EPOCH + timedelta(days=int(v))
    t = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime(t[: len(datetime.now().strftime(fmt))], fmt).date()
        except ValueError:
            continue
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", t)
    return date(int(m[1]), int(m[2]), int(m[3])) if m else None


def to_dt(v) -> datetime | None:
    if isinstance(v, datetime):
        return v
    if isinstance(v, (int, float)):
        return datetime.combine(EPOCH, time()) + timedelta(days=float(v))
    t = s(v)
    for fmt in ("%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(t, fmt)
        except ValueError:
            continue
    d = to_date(v)
    return datetime.combine(d, time()) if d else None


def to_time(v) -> time | None:
    if isinstance(v, time):
        return v.replace(second=0, microsecond=0)
    if isinstance(v, datetime):
        return v.time().replace(second=0, microsecond=0)
    if isinstance(v, (int, float)):
        mins = round((float(v) % 1) * 24 * 60)
        return time(mins // 60 % 24, mins % 60)
    m = re.match(r"(\d{1,2}):(\d{2})", s(v))
    return time(int(m[1]) % 24, int(m[2])) if m else None


def month_of(v) -> str:
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m")
    if isinstance(v, (int, float)) and v > 1000 and not 190001 <= v <= 210012:
        return (EPOCH + timedelta(days=int(v))).strftime("%Y-%m")
    return s(v)[:7]


def tg_id(v) -> int | None:
    t = re.sub(r"\D", "", s(v))
    return int(t) if t else None


# ------------------------------------------------------------------ report
@dataclass
class Report:
    counts: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    checks: list = field(default_factory=list)

    def add(self, key, n=1):
        self.counts[key] = self.counts.get(key, 0) + n

    def warn(self, msg):
        self.warnings.append(msg)

    def ok(self) -> bool:
        return all(c[0] for c in self.checks)

    def text(self) -> str:
        lines = ["Import natijasi:"]
        for k, v in self.counts.items():
            lines.append(f"  {k}: {v}")
        if self.warnings:
            lines.append(f"Ogohlantirishlar ({len(self.warnings)}):")
            lines += [f"  - {w}" for w in self.warnings[:200]]
            if len(self.warnings) > 200:
                lines.append(f"  … yana {len(self.warnings) - 200} ta")
        lines.append("Tekshiruv (jadval = baza):")
        lines += [f"  {'✅' if ok else '❌'} {msg}" for ok, msg in self.checks]
        return "\n".join(lines)


# ------------------------------------------------------------------ importer
class Importer:
    def __init__(self, source, report: Report | None = None):
        self.src = source
        self.r = report or Report()
        self.members: dict[int, TelegramMember] = {}

    def skip(self, sheet: str, row_no: int, why: str):
        """Every row that is not imported is reported — nothing disappears silently."""
        self.r.warn(f"{sheet}, {row_no}-qator: {why} — o'tkazib yuborildi")
        self.r.add(f"{sheet}: o'tkazib yuborildi")

    # ---------------- members & settings
    def member(self, tid: int, name: str = "") -> TelegramMember:
        if tid in self.members:
            return self.members[tid]
        m = TelegramMember.objects.filter(telegram_id=tid).first()
        if not m:
            # someone who booked money but is no longer in «Xodimlar»
            m = TelegramMember.objects.create(
                telegram_id=tid, name=(name or str(tid))[:255], role=TelegramRole.BLOCKED
            )
            self.r.add("Xodimlar: Amallar'dan tiklangan (bloklangan)")
            self.r.warn(
                f"Telegram ID {tid} ({name}) «Xodimlar»da yo'q edi — bloklangan a'zo sifatida qo'shildi"
            )
        self.members[tid] = m
        return m

    def import_members(self):
        rows = self.src.rows("Xodimlar") or []
        for i, row in enumerate(rows, 2):
            tid = tg_id(row.get("Telegram ID"))
            if not tid:
                self.skip("Xodimlar", i, "Telegram ID bo'sh")
                continue
            role = ROLE_MAP.get(s(row.get("Rol")).lower(), TelegramRole.PENDING)
            m = TelegramMember.objects.filter(telegram_id=tid).first()
            if m:
                m.name, m.username, m.role = (
                    s(row.get("Ism"))[:255] or m.name,
                    s(row.get("Username"))[:255],
                    role,
                )
                m.save()
            else:
                # not linked to a site account here: oauth_user.telegram_id is unverified
                m = TelegramMember.objects.create(
                    telegram_id=tid,
                    name=s(row.get("Ism"))[:255] or str(tid),
                    username=s(row.get("Username"))[:255],
                    role=role,
                )
            self.members[tid] = m
            self.r.add("Xodimlar")

    def import_settings(self):
        rows = self.src.rows("Sozlamalar") or []
        cfg = {s(r.get("Kalit")): r.get("Qiymat") for r in rows if s(r.get("Kalit"))}
        ints = {
            "ESLATMA_SOAT": "FIN_REMINDER_HOUR",
            "RAHBAR_HISOBOT_SOAT": "FIN_ADMIN_REPORT_HOUR",
            "OY_OXIRI_KUN": "FIN_MONTH_END_DAYS",
            "OGOHLANTIRISH_FOIZ": "FIN_WARN_PERCENT",
            "SAYT_TAYYOR_KUN": "FIN_READY_DAYS",
        }
        for old, new in ints.items():
            v = dec(cfg.get(old))
            if v:
                setattr(config, new, int(v))
        rate = dec(cfg.get("USD_KURS"))
        config.FIN_USD_RATE = float(rate) if rate else 0.0
        if s(cfg.get("CHANNEL_ID")):
            config.FIN_CHANNEL_ID = s(cfg.get("CHANNEL_ID"))
        for tid in [tg_id(x) for x in re.split(r"[,\s;]+", s(cfg.get("ADMIN_IDS")))]:
            if tid and tid in self.members:
                S.set_member_role(self.members[tid], TelegramRole.ADMIN)
        duties = {
            "SAYT_KIRITUVCHI": ("is_site_entry", []),
            "FIKR_XODIM": ("is_feedback", []),
            "SROK_XODIM": ("is_deadline_receiver", ["gafurov"]),
            "BONUS_XODIM": ("is_bonus_receiver", ["yusupov"]),
        }
        for key, (duty, hints) in duties.items():
            ids = [tg_id(x) for x in re.split(r"[,\s;]+", s(cfg.get(key))) if tg_id(x)]
            targets = [self.members[i] for i in ids if i in self.members]
            if not targets and hints:  # the Apps Script found these people by name
                targets = [
                    m
                    for m in self.members.values()
                    if m.is_active_member
                    and any(h in f"{m.name} {m.username}".lower() for h in hints)
                ]
            if not targets and duty == "is_deadline_receiver" and 254366051 in self.members:
                targets = [self.members[254366051]]
            for m in targets:
                setattr(m, duty, True)
                m.save(update_fields=[duty, "updated_at"])
                self.r.add(f"Vazifa: {duty}")
        self.r.add("Sozlamalar", len(cfg))

    # ---------------- catalogs
    def import_workers(self):
        rows = self.src.rows("Ishchilar")
        if rows is None:
            return
        for i, row in enumerate(rows):
            name = s(row.get("Ism"))
            if not name:
                self.skip("Ishchilar", i + 2, "ism bo'sh")
                continue
            Worker.objects.update_or_create(
                group=s(row.get("Bo'lim")) or "Boshqa",
                name=name,
                defaults={"position": s(row.get("Lavozim")), "ordering": i, "is_active": True},
            )
            self.r.add("Ishchilar")

    def import_orders(self):
        site_numbers = set(
            str(n)
            for n in S.Order.objects.exclude(order_number__isnull=True).values_list(
                "order_number", flat=True
            )
        )
        for row in self.src.rows("Buyurtmalar") or []:
            ref = s(row.get("ID"))[:32]
            if not ref or ref in site_numbers:
                continue
            ManualOrder.objects.update_or_create(
                ref=ref,
                defaults=dict(
                    client=s(row.get("Mijoz"))[:255],
                    phone=s(row.get("Telefon"))[:64],
                    price=dec(row.get("Shartnoma (so'm)")) or 0,
                    is_closed=s(row.get("Holat")) == "tugadi",
                    opened=to_date(row.get("Ochilgan")),
                    closed=to_date(row.get("Yopilgan")),
                ),
            )
            self.r.add("Buyurtmalar (saytda yo'q, qo'lda)")

    def category(self, code: str, name: str, kind: str, row_no: int) -> FinanceCategory:
        code = re.sub(r"[^a-z0-9_-]", "", code.lower())[:32]
        if not code:
            code = "boshqa_kirim" if kind == "income" else "boshqa"
            self.r.warn(f"Amallar, {row_no}-qator: kategoriya kodi bo'sh — «{code}» ga yozildi")
        c = FinanceCategory.objects.filter(code=code).first()
        if c:
            if c.kind != CategoryKind.INTERNAL and c.kind != kind:
                self.r.warn(
                    f"Amallar, {row_no}-qator: «{code}» kategoriyasi {c.get_kind_display().lower()} uchun, "
                    f"lekin bu qator {'kirim' if kind == 'income' else 'chiqim'} — saytda tahrirlashda kategoriyani o'zgartiring"
                )
            return c
        self.r.warn(f"Noma'lum kategoriya «{code}» ({name}) — faol emas holda qo'shildi")
        return FinanceCategory.objects.create(
            code=code,
            name=(name or code)[:128],
            kind=CategoryKind.INCOME if kind == "income" else CategoryKind.EXPENSE,
            is_active=False,
            ordering=200,
        )

    # ---------------- operations
    def import_operations(self):
        rows = self.src.rows("Amallar") or []
        existing = {o.number: o for o in Operation.objects.all()}
        orders = {
            str(n): oid
            for oid, n in S.Order.objects.exclude(order_number__isnull=True).values_list(
                "id", "order_number"
            )
        }
        sheet_sum = {}  # tid -> (income, expense) of rows the sheet itself counts
        imported_numbers = set()
        seen = set()
        for row_no, row in enumerate(rows, 2):
            num = tg_id(row.get("ID"))
            if not num:
                self.skip("Amallar", row_no, f"ID bo'sh yoki noto'g'ri ({s(row.get('ID')) or '—'})")
                continue
            tid = tg_id(row.get("Xodim ID"))
            amount = dec(row.get("Summa (so'm)"))
            day = to_date(row.get("Sana"))
            if not tid or amount is None or not day:
                self.skip("Amallar", row_no, f"#{num}: xodim, summa yoki sana bo'sh")
                continue
            kind = "income" if s(row.get("Turi")) == "Kirim" else "expense"
            deleted = s(row.get("O'chirildi")) == "Ha"
            if not deleted:
                inc, exp = sheet_sum.get(tid, (Decimal(0), Decimal(0)))
                sheet_sum[tid] = (inc + amount, exp) if kind == "income" else (inc, exp + amount)
            if num in seen:
                # still counted in the sheet totals above, so the check shows ❌
                self.skip("Amallar", row_no, f"#{num} ID jadvalda ikki marta uchraydi")
                continue
            seen.add(num)
            old = existing.get(num)
            if old and old.source != "import":
                self.r.warn(
                    f"Amallar #{num}: bu raqam yangi botda/saytda allaqachon band (#{num} {old.member.name}) — o'tkazib yuborildi"
                )
                self.r.add("Amallar: raqam to'qnashuvi")
                continue
            member = self.member(tid, s(row.get("Xodim")))
            author_id = tg_id(row.get("Kiritdi"))
            cur = s(row.get("Valyuta")) or "UZS"
            ref = s(row.get("Buyurtma ID"))[:32].lstrip("#")
            cat = self.category(
                s(row.get("Kategoriya kodi")), s(row.get("Kategoriya")), kind, row_no
            )
            values = dict(
                date=day,
                time=to_time(row.get("Vaqt")),
                member=member,
                author=self.member(author_id) if author_id else None,
                kind=kind,
                amount=amount,
                currency="USD" if cur == "USD" else "UZS",
                orig_amount=dec(row.get("Asl summa")) if cur == "USD" else None,
                rate=dec(row.get("Kurs")) if cur == "USD" else None,
                category=cat,
                order_ref=ref,
                order_id=orders.get(ref),
                comment=s(row.get("Izoh")),
                receipt_file_id=s(row.get("Chek")),
                worker=s(row.get("Ishchi (oylik)"))[:255],
                pay_type=(
                    s(row.get("Ish haqi turi"))
                    if s(row.get("Ish haqi turi")) in ("Avans", "Oylik")
                    else ""
                ),
                is_deleted=deleted,
                source="import",
            )
            if old:
                for k, v in values.items():
                    setattr(old, k, v)
                old.save()
            else:
                Operation.objects.create(number=num, **values)
            imported_numbers.add(num)
            self.r.add("Amallar")
        self._link_transfers(imported_numbers)
        self._mark_handover(imported_numbers)
        self._verify(sheet_sum, imported_numbers)

    def _link_transfers(self, numbers):
        """kirim «otkazma» rows start with «#<chiqim id>» (trSave_/handoverDo_)."""
        ops = {
            o.number: o
            for o in Operation.objects.filter(number__in=numbers, category__code="otkazma")
        }
        for o in ops.values():
            if o.kind != "income":
                continue
            m = re.match(r"#(\d+)(:|$)", o.comment)
            pair = ops.get(int(m[1])) if m else None
            if pair and pair.kind == "expense" and o.pair_id != pair.id:
                o.pair = pair
                o.save(update_fields=["pair"])
                self.r.add("O'tkazma juftlari")

    def _mark_handover(self, numbers):
        """«Pul oldim» money already handed to the boss («Rahbarga topshirdi … (#id)»)
        or dropped (deleted) must not show up in /topshiruv again."""
        handed = set()
        for c in Operation.objects.filter(
            number__in=numbers, comment__startswith="Rahbarga topshirdi"
        ).values_list("comment", flat=True):
            m = re.search(r"\(#(\d+)\)\s*$", c)
            if m:
                handed.add(int(m[1]))
        for o in Operation.objects.filter(
            number__in=numbers,
            category__code="qoldiq",
            comment__startswith="Pul oldim",
            handover="",
        ):
            if o.number in handed:
                o.handover = "accepted"
            elif o.is_deleted:
                o.handover = "deleted"
            else:
                continue
            o.save(update_fields=["handover"])
            self.r.add("Topshiruv belgilari")

    def _verify(self, sheet_sum, numbers):
        rows = Operation.objects.filter(number__in=numbers, is_deleted=False)
        total = {"income": Decimal(0), "expense": Decimal(0)}
        per = {}
        for tid, kind, amount in rows.values_list("member__telegram_id", "kind", "amount"):
            total[kind] += amount
            inc, exp = per.get(tid, (Decimal(0), Decimal(0)))
            per[tid] = (inc + amount, exp) if kind == "income" else (inc, exp + amount)
        s_inc = sum((v[0] for v in sheet_sum.values()), Decimal(0))
        s_exp = sum((v[1] for v in sheet_sum.values()), Decimal(0))
        self.r.checks.append(
            (s_inc == total["income"], f"Jami kirim: jadval {s_inc} = baza {total['income']}")
        )
        self.r.checks.append(
            (s_exp == total["expense"], f"Jami chiqim: jadval {s_exp} = baza {total['expense']}")
        )
        bad = []
        for tid, (inc, exp) in sheet_sum.items():
            got = per.get(tid, (Decimal(0), Decimal(0)))
            if (inc - exp) != (got[0] - got[1]):
                bad.append(f"{tid}: jadval {inc - exp}, baza {got[0] - got[1]}")
        self.r.checks.append(
            (
                not bad,
                f"Har bir hamyon balansi ({len(sheet_sum)} ta)"
                + (": " + "; ".join(bad[:10]) if bad else " — hammasi teng"),
            )
        )

    # ---------------- the rest
    def import_month_reports(self):
        for row_no, row in enumerate(self.src.rows("Oylik hisob") or [], 2):
            tid, ym = tg_id(row.get("Xodim ID")), month_of(row.get("Oy"))
            if not tid or not re.match(r"\d{4}-\d{2}$", ym):
                self.skip("Oylik hisob", row_no, "xodim ID yoki oy bo'sh")
                continue
            MonthReport.objects.update_or_create(
                member=self.member(tid, s(row.get("Xodim"))),
                month=ym,
                defaults=dict(
                    submitted_at=to_dt(row.get("Topshirildi")) or datetime.now(),
                    balance=dec(row.get("Qoldiq")) or 0,
                    note=s(row.get("Izoh")),
                ),
            )
            self.r.add("Oylik hisob")

    def import_bonuses(self):
        status = {"✅ Olindi": "done", "❌ 30 kundan o'tdi": "expired"}
        for row_no, row in enumerate(self.src.rows("Bonuslar") or [], 2):
            ref = s(row.get("Buyurtma ID"))[:32]
            ready = to_date(row.get("Готов sanasi"))
            if not ref or not ready:
                self.skip("Bonuslar", row_no, "buyurtma ID yoki Готов sanasi bo'sh")
                continue
            pct = dec(row.get("Foiz"))
            OrderBonus.objects.update_or_create(
                order_ref=ref,
                defaults=dict(
                    order=(
                        S.Order.objects.filter(order_number=int(ref)).first()
                        if ref.isdigit()
                        else None
                    ),
                    client=s(row.get("Mijoz"))[:255],
                    total=dec(row.get("Umumiy summa")) or 0,
                    currency=s(row.get("Valyuta")) or "UZS",
                    ready_date=ready,
                    rest=dec(row.get("Qoldiq (hozir)")),
                    paid_date=to_date(row.get("Pul olingan sana")),
                    days=int(dec(row.get("Kun"))) if dec(row.get("Kun")) is not None else None,
                    percent=(pct * 100 if pct is not None and pct < 1 else pct),
                    bonus=dec(row.get("Bonus (so'm)")),
                    status=status.get(s(row.get("Holat")), "waiting"),
                    note=s(row.get("Izoh"))[:255],
                    receiver=s(row.get("Kimga"))[:255],
                ),
            )
            self.r.add("Bonuslar")

    def import_warranty(self):
        for row_no, row in enumerate(self.src.rows("Kafolat xatlari") or [], 2):
            ref = s(row.get("Buyurtma ID"))[:32]
            if not ref:
                self.skip("Kafolat xatlari", row_no, "buyurtma ID bo'sh")
                continue
            given = s(row.get("Holat")).startswith("✅")
            WarrantyLetter.objects.update_or_create(
                order_ref=ref,
                defaults=dict(
                    client=s(row.get("Mijoz"))[:255],
                    ready_date=to_date(row.get("Готов sanasi")),
                    given=given,
                    given_at=to_date(row.get("Berilgan sana")),
                    given_by=s(row.get("Kim berdi"))[:255],
                    note=s(row.get("Izoh"))[:255],
                ),
            )
            self.r.add("Kafolat xatlari")

    def import_site_entry(self):
        for row_no, row in enumerate(self.src.rows("Saytga kiritish") or [], 2):
            code = s(row.get("Kod"))[:32]
            if not code:
                self.skip("Saytga kiritish", row_no, "kod bo'sh")
                continue
            SiteEntryTask.objects.update_or_create(
                code=code,
                defaults=dict(
                    date=to_date(row.get("Olingan sana")) or date.today(),
                    order_ref=s(row.get("Buyurtma ID"))[:32],
                    client=s(row.get("Mijoz"))[:255],
                    sum_text=s(row.get("Olingan summa"))[:255],
                    taken_by=s(row.get("Kim oldi"))[:255],
                    rest_text=s(row.get("Qoldiq (botda)"))[:255],
                    is_done=s(row.get("Holat")).startswith("✅"),
                    done_at=to_date(row.get("Kiritilgan sana")),
                    done_by=s(row.get("Kim kiritdi"))[:255],
                ),
            )
            self.r.add("Saytga kiritish")

    def import_feedback(self):
        rows = self.src.rows("Mijoz fikrlari") or []
        links = {}
        for row in self.src.rows("Mijoz fikrlari", formulas=True) or []:
            m = re.search(r'HYPERLINK\("([^"]+)"', s(row.get("Skrinshot")))
            if m:
                links[s(row.get("Buyurtma ID"))] = m[1]
        for row_no, row in enumerate(rows, 2):
            ref = s(row.get("Buyurtma ID"))[:32]
            if not ref:
                self.skip("Mijoz fikrlari", row_no, "buyurtma ID bo'sh")
                continue
            got = s(row.get("Holat")).startswith("✅")
            ClientFeedback.objects.update_or_create(
                order_ref=ref,
                defaults=dict(
                    client=s(row.get("Mijoz"))[:255],
                    phone=s(row.get("Telefon"))[:64],
                    ready_date=to_date(row.get("Готов sanasi")),
                    asked_date=to_date(row.get("So'ralgan sana")),
                    status="received" if got else "asked",
                    received_date=to_date(row.get("Olingan sana")),
                    received_by=s(row.get("Kim oldi"))[:255],
                    text=s(row.get("Fikr (izoh)")),
                    screenshot_url=links.get(ref, "")[:500],
                ),
            )
            self.r.add("Mijoz fikrlari")

    def run(self) -> Report:
        with transaction.atomic():
            self.import_members()
            self.import_settings()
            self.import_workers()
            self.import_orders()
            self.import_operations()
            self.import_month_reports()
            self.import_bonuses()
            self.import_warranty()
            self.import_site_entry()
            self.import_feedback()
            if not str(config.FIN_BONUS_SINCE or "").strip():
                # Готов orders older than today were handled by the old bot
                config.FIN_BONUS_SINCE = date.today().isoformat()
        return self.r
