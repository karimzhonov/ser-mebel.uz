"""Import of the Apps Script davomat into the hr tables.

Two sources in the same Google spreadsheet:
- «Davomat»: one row per employee per finished day (what finalizeDay_ wrote).
- «DavomatExport»: the dv_* ScriptProperties written by docs/davomat_export.gs —
  employees, settings, groups, holidays, leaves, extra points, winners and the days
  not yet written to the sheet.

Safe to re-run: employees by Telegram ID, days by (employee, day), the rest by their
natural keys. Every skipped row is reported; at the end the number of day rows and
each employee's points are compared with the sheet.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta

from django.db import transaction

from accounting.importer import Report, s, tg_id, to_date, to_time

from . import services as S
from .constants import DEFAULTS, ST_PLAIN
from .models import (
    Attendance,
    Employee,
    Holiday,
    HolidayDecision,
    HrSetting,
    Leave,
    PointAdjustment,
    Winner,
    WorkGroup,
)

STATUS_BY_LABEL = {v: k for k, v in ST_PLAIN.items()}


def _int(v):
    try:
        return int(float(str(v).replace(",", ".")))
    except (TypeError, ValueError):
        return None


def _day(v) -> date | None:
    return to_date(v)


class DavomatImporter:
    def __init__(self, source, report: Report | None = None):
        self.src = source
        self.r = report or Report()
        self.props: dict[str, str] = {}
        self.groups: dict[int, WorkGroup] = {}
        self.live_from_sheet: set[int] = set()

    def skip(self, sheet, row_no, why):
        self.r.warn(f"{sheet}, {row_no}-qator: {why} — o'tkazib yuborildi")
        self.r.add(f"{sheet}: o'tkazib yuborildi")

    # ---------------------------------------------------------- ScriptProperties
    def load_props(self):
        rows = self.src.rows("DavomatExport")
        if rows is None:
            self.r.warn(
                "«DavomatExport» varag'i yo'q — xodimlar sozlamalari (ish vaqti, dam kunlari), ta'tillar, "
                "qo'shimcha ballar va guruhlar import qilinmaydi. Avval Apps Script'da davomatExport() ni ishga tushiring."
            )
            return
        for row in rows:
            k = s(row.get("Kalit"))
            if k.startswith("dv_"):
                self.props[k[3:]] = s(row.get("Qiymat"))

    def j(self, key, default=None):
        try:
            return json.loads(self.props[key])
        except (KeyError, ValueError):
            return default

    def import_groups(self):
        for chat_id, title in (self.j("groups", {}) or {}).items():
            cid = _int(chat_id)
            if cid is None:
                continue
            g, _ = WorkGroup.objects.update_or_create(
                chat_id=cid, defaults={"title": str(title)[:255], "is_active": True}
            )
            self.groups[cid] = g
            self.r.add("Guruhlar")

    def import_settings(self):
        for k in DEFAULTS:
            if f"s_{k}" in self.props:
                HrSetting.objects.update_or_create(
                    key=k, defaults={"value": self.props[f"s_{k}"][:255]}
                )
                self.r.add("Sozlamalar")
        S.clear_settings_cache()
        for k in ("since",):
            if self.props.get(k):
                S.set_state("SINCE", self.props[k][:10])

    def import_employees(self):
        from accounting.services import member_by_tg

        for key in sorted(k for k in self.props if k.startswith("e_")):
            e = self.j(key)
            if not isinstance(e, dict) or not _int(e.get("tg")):
                self.r.warn(f"DavomatExport: {key} o'qilmadi — o'tkazib yuborildi")
                continue
            tid = int(e["tg"])
            g = self.groups.get(_int(e.get("g"))) if e.get("g") else None
            off = e.get("off")
            values = dict(
                name=str(e.get("n") or tid)[:255],
                username=str(e.get("u") or "")[:255],
                is_active=bool(e.get("a")),
                # the new bot can only write to people who pressed /start in IT
                can_dm=None,
                off_days=[int(x) for x in off] if isinstance(off, list) else None,
                group=g,
                work_start=str(e.get("ws") or "")[:5],
                work_end=str(e.get("we") or "")[:5],
                created_on=_day(e.get("c")),
                member=member_by_tg(tid),
            )
            emp = Employee.objects.filter(telegram_id=tid).first()
            if emp:
                # already here (earlier import or the new bot): site edits win
                self.r.add("Xodimlar: bazada bor (o'zgartirilmadi)")
                continue
            else:
                num = _int(e.get("id"))
                if not num or Employee.objects.filter(number=num).exists():
                    num = (
                        max(Employee.objects.values_list("number", flat=True), default=0) or 0
                    ) + 1
                Employee.objects.create(telegram_id=tid, number=num, **values)
            self.r.add("Xodimlar")

    def employee(self, tid: int, name: str, username: str) -> Employee:
        e = Employee.objects.filter(telegram_id=tid).first()
        if e:
            return e
        num = (max(Employee.objects.values_list("number", flat=True), default=0) or 0) + 1
        self.r.warn(
            f"Telegram ID {tid} ({name}) davomat xotirasida yo'q edi — jadvaldan tiklandi (faol emas)"
        )
        self.r.add("Xodimlar: jadvaldan tiklangan")
        return Employee.objects.create(
            telegram_id=tid,
            number=num,
            name=name[:255] or str(tid),
            username=username.lstrip("@")[:255],
            is_active=False,
        )

    # ---------------------------------------------------------- the «Davomat» sheet
    def import_days(self):
        """«Davomat» rows. Days before the Apps Script's open day (CURDAY) are frozen
        with points recomputed by pointsOf_ (the sheet's «Ball» column was never the
        source for stats — readSheet_ recomputed it). The open day and anything after
        it stays live: the bot's memory rows (dv_a_*) are richer and the new
        scheduler finalizes it. Existing rows are never overwritten (site corrections
        win over a re-import)."""
        rows = self.src.rows("Davomat")
        if rows is None:
            self.r.warn("«Davomat» varag'i yo'q.")
            return
        open_from = _day(self.props.get("curday"))
        if not open_from:
            days = [_day(r.get("Sana")) for r in rows]
            last = max((d for d in days if d), default=None)
            open_from = last + timedelta(days=1) if last else None
        frozen = 0
        sheet_frozen = 0
        diffs = []
        seen = set()
        for row_no, row in enumerate(rows, 2):
            day = _day(row.get("Sana"))
            tid = tg_id(row.get("Telegram ID"))
            if not day and not tid:
                continue  # rows used only by the summary block (column T…)
            if not day or not tid:
                self.skip("Davomat", row_no, "sana yoki Telegram ID bo'sh")
                continue
            label = s(row.get("Holat"))
            st = STATUS_BY_LABEL.get(label)
            if not st:
                self.skip("Davomat", row_no, f"noma'lum holat «{label}»")
                continue
            if (tid, day) in seen:
                self.skip("Davomat", row_no, f"{day} {tid} ikki marta yozilgan")
                continue
            seen.add((tid, day))
            is_open = (open_from and day >= open_from) or st == "waiting"
            if not is_open:
                sheet_frozen += 1
            e = self.employee(tid, s(row.get("Xodim")), s(row.get("Username")))
            if Attendance.objects.filter(employee=e, day=day).exists():
                self.r.add("Davomat kunlari: bazada bor (o'zgartirilmadi)")
                frozen += 0 if is_open else 1
                continue
            hours = re.split(r"[–-]", s(row.get("Ish vaqti")))
            er = s(row.get("Erta ketish sababi"))
            izoh = s(row.get("Izoh"))
            uni = s(row.get("Forma"))
            a = Attendance(
                employee=e,
                day=day,
                # a live row keeps only what the bot itself had decided
                status=st if not is_open or st in ("on_time", "late", "excused", "off") else "",
                in_time=to_time(row.get("Kelgan vaqti")),
                late_min=_int(row.get("Kechikish (daq)")),
                late_reason=s(row.get("Kechikish sababi"))[:16],
                late_comment=izoh if st == "late" else "",
                note=izoh[:255] if st != "late" else "",
                excuse=izoh if st == "excused" else "",
                eta=to_time(row.get("Aytgan vaqti")),
                uniform=True if uni == "Ha" else (False if uni == "Yo'q" else None),
                out_time=to_time(row.get("Ketgan vaqti")),
                early_min=_int(row.get("Erta ketish (daq)")),
                early_reason="Sababli" if er.startswith("Sababli") else ("Sababsiz" if er else ""),
                early_comment=re.sub(r"^Sabab(li|siz):?\s*", "", er),
                no_checkin=st == "noin",
                work_start=hours[0].strip()[:5] if hours and hours[0] else "",
                work_end=hours[1].strip()[:5] if len(hours) > 1 else "",
                group_title=s(row.get("Filial (guruh)"))[:255],
                finalized=not is_open,
            )
            if not is_open:
                r = S.Row(e, st, a, a.note)
                a.points = S.row_points(r, day, S.now(), final=True) if S.scored(r) else None
                sheet_pts = _int(row.get("Ball"))
                if sheet_pts is not None and sheet_pts != a.points:
                    diffs.append(
                        f"{day} {e.name}: jadvalda {sheet_pts}, qoidalar bo'yicha {a.points}"
                    )
                frozen += 1
            a.save()
            if is_open:
                self.live_from_sheet.add(a.pk)
            self.r.add("Davomat kunlari" + (" (ochiq kun — jonli)" if is_open else ""))
        if diffs:
            self.r.warn(
                f"{len(diffs)} ta kunda jadvaldagi «Ball» qoidalar bo'yicha hisoblangandan farq qiladi "
                "(eski versiya yoki qo'lda o'zgartirilgan) — qoidalar bo'yicha yozildi: "
                + "; ".join(diffs[:10])
            )
        self.r.checks.append(
            (
                frozen == sheet_frozen,
                f"Yakunlangan kunlar: jadvalda {sheet_frozen}, bazada {frozen}",
            )
        )

    def import_open_days(self):
        """dv_a_<day>_<tg>: days still in the Apps Script memory (today / not yet in
        the sheet). Imported as live rows; the scheduler finalizes them."""
        for key in sorted(k for k in self.props if k.startswith("a_")):
            m = re.fullmatch(r"a_(\d{4}-\d{2}-\d{2})_(\d+)", key)
            a = self.j(key)
            if not m or not isinstance(a, dict):
                continue
            day, tid = date.fromisoformat(m[1]), int(m[2])
            e = Employee.objects.filter(telegram_id=tid).first()
            existing = Attendance.objects.filter(employee=e, day=day).first() if e else None
            if not e or (existing and existing.pk not in self.live_from_sheet):
                continue  # already written by the new bot (or frozen): keep it
            uni = a.get("uni")
            Attendance.objects.update_or_create(
                employee=e,
                day=day,
                defaults=dict(
                    status=str(a.get("st") or "")[:16],
                    in_time=to_time(a.get("in")),
                    late_min=_int(a.get("late")),
                    late_reason=str(a.get("lr") or "")[:16],
                    late_comment=str(a.get("lc") or ""),
                    link=str(a.get("link") or "")[:300],
                    work_start=str(a.get("ws") or "")[:5],
                    work_end=str(a.get("we") or "")[:5],
                    out_time=to_time(a.get("out")),
                    early_min=_int(a.get("early")),
                    early_reason=str(a.get("er") or "")[:16],
                    early_comment=str(a.get("ec") or ""),
                    no_checkin=bool(a.get("noin")),
                    uniform=True if uni == 1 else (False if uni == 0 else None),
                    eta=to_time(a.get("eta")),
                    eta_sent=bool(a.get("etaSent")),
                    asked=_int(a.get("asked")) or 0,
                    wait=str(a.get("wait") or "")[:8],
                    warned=bool(a.get("warned")),
                    off_requested=bool(a.get("offReq")),
                    excuse=str(a.get("rsn") or ""),
                    finalized=False,
                ),
            )
            self.r.add("Ochiq kunlar (xotiradan)")

    def import_calendar(self):
        for d, name in (self.j("holidays", {}) or {}).items():
            dd = _day(d)
            if dd:
                Holiday.objects.update_or_create(day=dd, defaults={"name": str(name)[:128]})
                self.r.add("Bayramlar")
        for key in (k for k in self.props if k.startswith("hd_")):
            dd = _day(key[3:])
            if dd:
                HolidayDecision.objects.update_or_create(
                    holiday_day=dd, defaults={"days": _int(self.props[key]) or 0}
                )
        for lv in self.j("leaves", []) or []:
            e = Employee.objects.filter(telegram_id=_int(lv.get("tg"))).first()
            d_from, d_to, num = _day(lv.get("from")), _day(lv.get("to")), _int(lv.get("id"))
            if not e or not d_from or not d_to or not num:
                self.r.warn(
                    f"Ta'til #{lv.get('id')}: xodim yoki sana topilmadi — o'tkazib yuborildi"
                )
                continue
            Leave.objects.update_or_create(
                number=num,
                defaults={
                    "employee": e,
                    "date_from": d_from,
                    "date_to": d_to,
                    "reason": str(lv.get("r") or "ta'til")[:255],
                },
            )
            self.r.add("Ta'tillar")

    def import_points_and_winners(self):
        for key in (k for k in self.props if k.startswith("adj_")):
            for x in self.j(key, []) or []:
                e = Employee.objects.filter(telegram_id=_int(x.get("tg"))).first()
                d = _day(x.get("d"))
                if not e or not d or not _int(x.get("v")):
                    self.r.warn(f"Qo'shimcha ball {key}: yozuv o'qilmadi — o'tkazib yuborildi")
                    continue
                PointAdjustment.objects.get_or_create(
                    employee=e, day=d, value=_int(x["v"]), reason=str(x.get("r") or "")[:255]
                )
                self.r.add("Qo'shimcha ballar")
        for key in (k for k in self.props if k.startswith("win_")):
            m = re.fullmatch(r"win_([my])_(.+)", key)
            e = Employee.objects.filter(telegram_id=_int(self.props[key])).first()
            if m and e:
                Winner.objects.update_or_create(
                    kind=m[1], period=m[2][:7], defaults={"employee": e}
                )
                self.r.add("Oy/yil xodimlari")

    def run(self) -> Report:
        with transaction.atomic():
            self.load_props()
            self.import_groups()
            self.import_settings()
            self.import_employees()
            self.import_days()
            self.import_open_days()
            self.import_calendar()
            self.import_points_and_winners()
            # Go-live = today. Open (non-finalized) rows before today are finalized by the
            # scheduler; days with no data between the Apps Script stop and today are
            # NOT turned into «Kelmadi» — nobody could report then.
            if not S.state("CURDAY"):
                S.set_state("CURDAY", S.now().date().isoformat())
        return self.r
