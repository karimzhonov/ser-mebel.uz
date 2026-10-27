"""Inline keyboards of the davomat bot. Every callback_data starts with `dv:` (the old
prefix), so buttons already sitting in chats keep working."""

from __future__ import annotations

from datetime import date

from aiogram.types import InlineKeyboardMarkup

from bot.common.kb import b, ik, url_button

from .fmt import fmt_day
from .texts import IV_PRESETS, REASONS, WD_SHORT

PREFIX = "dv:"


def dv(rows) -> InlineKeyboardMarkup:
    """rows of (text, data) pairs -> inline keyboard with the `dv:` prefix."""
    return ik([[b(t, PREFIX + d) for t, d in r] for r in rows if r])


def uniform_kb(day: date | str) -> InlineKeyboardMarkup:
    d = day if isinstance(day, str) else day.isoformat()
    return dv([[("👕 Ha, formadaman", f"uni:{d}:1"), ("Yo'q", f"uni:{d}:0")]])


def late_reason_kb(day: str) -> InlineKeyboardMarkup:
    return dv([[("✅ Sababli", f"lr:{day}:1"), ("❌ Sababsiz", f"lr:{day}:0")]])


def early_reason_kb(day: str) -> InlineKeyboardMarkup:
    return dv([[("✅ Sababli / kelishilgan", f"er:{day}:1"), ("❌ Sababsiz", f"er:{day}:0")]])


def eta_kb(day: date | str) -> InlineKeyboardMarkup:
    d = day if isinstance(day, str) else day.isoformat()
    return dv(
        [
            [
                ("10 daqiqa", f"eta:{d}:10"),
                ("20 daqiqa", f"eta:{d}:20"),
                ("30 daqiqa", f"eta:{d}:30"),
            ],
            [("1 soat", f"eta:{d}:60"), ("2 soat", f"eta:{d}:120")],
            [("✅ Keldim, otchet tashlayman", f"here:{d}")],
            [("😴 Bugun dam olish kunim", f"offreq:{d}")],
            [("🚫 Bugun kela olmayman", f"cant:{d}")],
        ]
    )


def reason_kb(day: date | str) -> InlineKeyboardMarkup:
    d = day if isinstance(day, str) else day.isoformat()
    rows = [[(v, f"rsn:{d}:{k}")] for k, v in REASONS.items()]
    rows.append([("✏️ Boshqa (o'zim yozaman)", f"rsn:{d}:other")])
    return dv(rows)


def connect_kb(url: str) -> InlineKeyboardMarkup:
    return ik([[url_button("🤖 Botga ulanish", url)]])


# ------------------------------------------------------------------ admin
def admin_menu_kb() -> InlineKeyboardMarkup:
    return dv(
        [
            [("📊 Bugungi holat", "m:today"), ("📅 Shu oy", "m:month")],
            [("👥 Xodimlar", "m:emps"), ("😴 Dam kunlari", "m:off")],
            [("🕐 Ish vaqtlari", "m:iv"), ("🏆 Reyting", "m:rank")],
            [("🎉 Bayramlar", "m:hol"), ("⚙️ Sozlamalar", "m:set")],
            [("🌐 Saytda ochish", "m:sheet"), ("❓ Buyruqlar", "m:help")],
        ]
    )


def emp_picker_kb(emps: list[dict], page: int, mode: str = "") -> InlineKeyboardMarkup:
    """emps: Employee DTOs (active ones). mode "iv" = working hours, "" = off days."""
    iv = mode == "iv"
    per = 30
    sl = emps[page * per : page * per + per]
    rows = []
    for i in range(0, len(sl), 2):
        row = []
        for e in sl[i : i + 2]:
            if iv:
                row.append(
                    (
                        f"{e['name']} ({e['hours_label']}{'' if e.get('work_start') else '*'})",
                        f"iv:{e['telegram_id']}",
                    )
                )
            else:
                off = e.get("off_days_effective") or []
                row.append(
                    (
                        e["name"] + (f" ({','.join(WD_SHORT[d - 1] for d in off)})" if off else " ⚠️"),
                        f"dk:{e['telegram_id']}",
                    )
                )
        rows.append(row)
    pk = "ivp:" if iv else "dkp:"
    nav = []
    if page > 0:
        nav.append(("⬅️", f"{pk}{page - 1}"))
    if len(emps) > (page + 1) * per:
        nav.append(("➡️", f"{pk}{page + 1}"))
    if nav:
        rows.append(nav)
    return dv(rows)


def iv_kb(e: dict, general: tuple[str, str]) -> InlineKeyboardMarkup:
    """general: (start, end) of the company-wide hours, shown on the «Umumiy vaqt» button."""
    rows = []
    for ws, we in IV_PRESETS:
        cur = e.get("work_start") == ws and e.get("work_end") == we
        rows.append(
            [
                (
                    ("✅ " if cur else "") + f"{ws} – {we}",
                    f"ivs:{e['telegram_id']}:{ws.replace(':', '')}-{we.replace(':', '')}",
                )
            ]
        )
    rows.append([(f"Umumiy vaqt ({general[0]} – {general[1]})", f"ivs:{e['telegram_id']}:0")])
    rows.append([("⬅️ Ro'yxatga qaytish", "ivp:0")])
    return dv(rows)


def off_days_kb(e: dict) -> InlineKeyboardMarkup:
    off = e.get("off_days") or []
    tg = e["telegram_id"]
    r1 = [(("✅ " if d in off else "") + WD_SHORT[d - 1], f"dkt:{tg}:{d}") for d in range(1, 5)]
    r2 = [(("✅ " if d in off else "") + WD_SHORT[d - 1], f"dkt:{tg}:{d}") for d in range(5, 8)]
    return dv([r1, r2, [("✔️ Tayyor", f"dkd:{tg}")], [("⬅️ Ro'yxatga qaytish", "dkp:0")]])


def reset_kb(today: date, tomorrow: date) -> InlineKeyboardMarkup:
    return dv(
        [
            [(f"📅 Ertadan ({fmt_day(tomorrow)})", f"rst:{tomorrow.isoformat()}")],
            [("📅 Bugundan", f"rst:{today.isoformat()}")],
            [("❌ Bekor qilish", "rst:no")],
        ]
    )


def holiday_ask_kb(day: str) -> InlineKeyboardMarkup:
    return dv(
        [
            [("Yo'q, ishlaymiz", f"hol:{day}:0")],
            [("1 kun", f"hol:{day}:1"), ("2 kun", f"hol:{day}:2"), ("3 kun", f"hol:{day}:3")],
            [("✏️ Boshqa (yozaman)", f"hol:{day}:x")],
        ]
    )


def off_request_kb(day: str, tg: int) -> InlineKeyboardMarkup:
    return dv([[("✅ Tasdiqlash", f"offok:{day}:{tg}"), ("❌ Rad etish", f"offno:{day}:{tg}")]])


def winner_kb(kind: str, period: str, rows: list[dict]) -> InlineKeyboardMarkup:
    """Buttons `dv:ann:{m|y}:{period}:{telegram_id}` for the first three."""
    medals = ["🥇", "🥈", "🥉"]
    return ik(
        [
            [b(f"{medals[i]} {r['name']} — e'lon qilish", f"dv:ann:{kind}:{period}:{r['telegram_id']}")]
            for i, r in enumerate(rows[:3])
        ]
    )

