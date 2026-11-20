"""«👷 Ishchi kartasi» → the worker's own folder: personal data (passport, prava, ish
staji), the files (passport / prava scans, contracts, every month's salary sheet —
past months uploaded by hand too) and the month-by-month salary history.

Files are kept in the DB (WorkerFile.data), like the salary template: a passport scan
under public /media/ would be readable by anyone who guesses the link.
"""

from __future__ import annotations

import os
import re
from datetime import date
from decimal import Decimal

from core.exceptions import ServiceError

from . import salary as SAL
from . import services as S
from .constants import PayType
from .models import Worker, WorkerFile
from .text import add_months, today

MAX_FILE = 10 * 1024 * 1024
MAX_PRIOR_MONTHS = 70 * 12
ZERO = Decimal(0)

# Only formats a browser never runs; the download is always an attachment anyway.
CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

PROFILE_FIELDS = [
    "birth_date",
    "phone",
    "address",
    "passport_number",
    "passport_issued_by",
    "passport_issued_on",
    "passport_expires",
    "pinfl",
    "license_number",
    "license_categories",
    "license_expires",
    "hired_on",
    "prior_experience_months",
    "experience_note",
]


# ------------------------------------------------------------------ personal data
def months_between(start: date, end: date) -> int:
    """Whole months from `start` to `end` (0 when end is before start)."""
    n = (end.year - start.year) * 12 + end.month - start.month
    if end.day < start.day:
        n -= 1
    return max(n, 0)


def experience_months(worker: Worker, on: date | None = None) -> dict:
    """Ish staji: before us (typed by hand) + here since `hired_on`."""
    here = months_between(worker.hired_on, on or today()) if worker.hired_on else 0
    prior = worker.prior_experience_months or 0
    return {"here": here, "prior": prior, "total": here + prior}


def update_profile(worker: Worker, **fields) -> Worker:
    """Save the personal data (only PROFILE_FIELDS; types already parsed)."""
    unknown = set(fields) - set(PROFILE_FIELDS)
    if unknown:
        raise ServiceError(f"Noma'lum maydon: {', '.join(sorted(unknown))}")
    for key in ("phone", "address", "passport_issued_by", "experience_note"):
        if key in fields:
            fields[key] = str(fields[key] or "").strip()
    if "passport_number" in fields:
        # «aa 1234567» / «AA1234567» → «AA 1234567»
        raw = re.sub(r"\s+", "", str(fields["passport_number"] or "")).upper()
        m = re.fullmatch(r"([A-Z]{2})(\d+)", raw)
        fields["passport_number"] = f"{m.group(1)} {m.group(2)}" if m else raw
    if "license_number" in fields:
        fields["license_number"] = " ".join(str(fields["license_number"] or "").split()).upper()
    if "license_categories" in fields:
        cats = re.split(r"[\s,;]+", str(fields["license_categories"] or "").upper())
        fields["license_categories"] = ", ".join(c for c in cats if c)
    if "pinfl" in fields:
        pinfl = re.sub(r"\s+", "", str(fields["pinfl"] or ""))
        if pinfl and not re.fullmatch(r"\d{14}", pinfl):
            raise ServiceError("JShShIR — 14 ta raqam.", "pinfl")
        fields["pinfl"] = pinfl
    if "prior_experience_months" in fields:
        n = fields["prior_experience_months"] or 0
        if not 0 <= n <= MAX_PRIOR_MONTHS:
            raise ServiceError("Oldingi staj noto'g'ri.", "prior_experience_months")
        fields["prior_experience_months"] = n
    t = today()
    for key in ("birth_date", "hired_on", "passport_issued_on"):
        if fields.get(key) and fields[key] > t:
            raise ServiceError("Bu sana kelajakda bo'lishi mumkin emas.", key)
    for key, value in fields.items():
        limit = getattr(Worker._meta.get_field(key), "max_length", None)
        if limit and isinstance(value, str) and len(value) > limit:
            raise ServiceError(f"Juda uzun ({limit} belgigacha).", key)
    if not fields:
        return worker
    for key, value in fields.items():
        setattr(worker, key, value)
    worker.save(update_fields=list(fields))
    return worker


# ------------------------------------------------------------------ files
def _clean_month(month) -> date | None:
    """«2026-10» / «2026-10-15» / a date → the 1st of that month."""
    if not month:
        return None
    if isinstance(month, date):
        d = month
    else:
        try:
            s = str(month).strip()
            d = date.fromisoformat(s if len(s) > 7 else f"{s}-01")
        except ValueError as e:
            raise ServiceError("Oy noto'g'ri (YYYY-MM).", "month") from e
    return d.replace(day=1)


def save_file(
    worker: Worker,
    *,
    kind: str,
    name: str,
    content: bytes,
    month=None,
    comment: str = "",
    user=None,
) -> WorkerFile:
    if kind not in WorkerFile.Kind.values:
        raise ServiceError("Fayl turini tanlang.", "kind")
    name = os.path.basename(str(name or "").replace("\\", "/"))
    name = re.sub(r"[\x00-\x1f\x7f]+", " ", name).strip()
    ext = os.path.splitext(name)[1].lower()
    if ext not in CONTENT_TYPES:
        raise ServiceError(
            "Bunday faylni yuklab bo'lmaydi: PDF, rasm (JPG, PNG, HEIC), Word yoki Excel.",
            "file",
        )
    if not content:
        raise ServiceError("Fayl bo'sh.", "file")
    if len(content) > MAX_FILE:
        raise ServiceError("Fayl juda katta (10 MB gacha).", "file")
    m = _clean_month(month)
    if kind == WorkerFile.Kind.SALARY:
        if m is None:
            raise ServiceError("Oylik varaqasi qaysi oy uchun — oyni tanlang.", "month")
        # the month the salary is FOR (salary.period): with a pay day early in the
        # month, «Oylik chiqarish» already works on next month's salary
        last = max(date.fromisoformat(SAL.next_month(worker) + "-01"), today().replace(day=1))
        if m > last:
            raise ServiceError("Kelgusi oy uchun oylik varaqasi yuklab bo'lmaydi.", "month")
    else:
        m = None  # only salary sheets belong to a month
    return WorkerFile.objects.create(
        worker=worker,
        kind=kind,
        month=m,
        name=name[-255:],
        content_type=CONTENT_TYPES[ext],
        size=len(content),
        data=content,
        comment=str(comment or "").strip()[:255],
        uploaded_by=user,
    )


def delete_file(f: WorkerFile) -> None:
    f.delete()


def files(worker: Worker):
    """Every file of the worker without the bytes."""
    return worker.files.defer("data").select_related("uploaded_by")


# ------------------------------------------------------------------ salary history
def salary_month_of(worker: Worker, d: date) -> str:
    """Which salary month a payment on `d` counts for — the same periods as «Oylik
    chiqarish» (salary.period): up to the pay day it is this month's, after it the
    next month's. Without a pay day — the calendar month."""
    ym = d.strftime("%Y-%m")
    return ym if d <= SAL.pay_date(worker, ym) else add_months(ym, 1)


def _worker_ops(worker: Worker):
    """This worker's salary operations, narrowed in the DB (name case/space-insensitive
    like services._worker_key) — not every salary the company ever paid."""
    words = worker.name.split()
    if not words:
        return S.salary_ops().none()
    pattern = r"^\s*" + r"\s+".join(re.escape(w) for w in words) + r"\s*$"
    return (
        S.salary_ops()
        .filter(worker__iregex=pattern)
        .select_related(None)
        .only("date", "pay_type", "amount", "worker")
    )


def salary_months(worker: Worker) -> list[dict]:
    """Every salary month (salary_month_of) with avans / oylik / uy uchun / total paid
    for it, plus the salary sheets uploaded for that month — newest first. Months that
    only have a sheet (uploaded for the time before the bot) show too."""
    key = S._worker_key(worker.name)
    out: dict[str, dict] = {}

    def month(ym: str) -> dict:
        return out.setdefault(
            ym,
            {
                "month": ym,
                "advance": ZERO,
                "salary": ZERO,
                "home": ZERO,
                "other": ZERO,
                "total": ZERO,
                "count": 0,
                "files": [],
            },
        )

    for t in _worker_ops(worker):
        if S._worker_key(t.worker) != key:
            continue
        x = month(salary_month_of(worker, t.date))
        slot = {
            PayType.ADVANCE: "advance",
            PayType.SALARY: "salary",
            PayType.HOME: "home",
        }.get(t.pay_type, "other")
        x[slot] += t.amount
        x["total"] += t.amount
        x["count"] += 1
    for f in files(worker).filter(kind=WorkerFile.Kind.SALARY, month__isnull=False):
        month(f.month.strftime("%Y-%m"))["files"].append(f)
    return [out[k] for k in sorted(out, reverse=True)]
