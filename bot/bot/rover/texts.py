"""Strings of the rover bot part (Uzbek). Everything from the backend is HTML-escaped."""

from __future__ import annotations

import html
from datetime import date, datetime

from bot.common.fmt import cur_name, esc, fmt_cur

CONFIRM_ASK = "❓ Rover ishi bajarilganini tasdiqlaysizmi?"
DONE_OK = "✅ Tasdiqlandi"
HEADER = "🛠 <b>Rover ishini tekshiring</b>"


def _dt(iso) -> str:
    s = str(iso or "")
    try:
        return f"{datetime.fromisoformat(s.replace('Z', '+00:00')):%d.%m %H:%M}"
    except ValueError:
        return s


def card(t: dict, by_name: str | None = None) -> str:
    """Card text from a RoverTask DTO; `by_name` is the fallback name of the checker."""
    order = t.get("order") or {}
    client = t.get("client") or {}
    lines = [HEADER, "", f"Buyurtma №{esc(order.get('number'))}"]
    if client.get("fio"):
        lines.append(f"👤 {esc(client['fio'])}")
    if client.get("phone"):
        lines.append(f"📞 {esc(client['phone'])}")
    lines.append(f"📐 Maydon: {esc(t.get('square'))} m²")
    cur = t.get("currency") or "UZS"
    lines.append(f"💰 Summa: {esc(fmt_cur(t.get('amount'), cur))} {cur_name(cur)}")
    who = (t.get("submitted_by") or {}).get("name")
    when = _dt(t.get("submitted_at")) if t.get("submitted_at") else ""
    if who or when:
        lines.append(f"👷 Bajardi: {esc(who or '—')} {esc(when)}".rstrip())
    if (t.get("note") or "").strip():
        lines.append(f"📝 Izoh: {esc(t['note'])}")
    if t.get("state") == "done":
        checker = (t.get("checked_by") or {}).get("name") or by_name
        lines.append("")
        lines.append(f"✅ Tasdiqlandi — {esc(checker or '—')}")
    return "\n".join(lines)


# ---- worker task card / head deadline card
TASK_HEADER = "🛠 <b>Yangi Rover ishi</b>"
HEAD_HEADER = "🗓 <b>Rover uchun muddat qo'ying</b>"
BUSY = "Avval boshqa amalni tugating"
CANCELLED = "Bekor qilindi."
STALE = "Bu tugma eskirgan."
ASK_AMOUNT = "Bajarilgan ish summasini yozing (so'm), masalan: 250 000"
BAD_AMOUNT = "❗ Summa noto'g'ri. Faqat butun son yozing, masalan: 250 000"
ASK_NOTE = "Izoh yozing: nima ish qilindi, nechta eshik"
BAD_NOTE = "❗ Izoh juda qisqa (kamida 3 belgi)."
LONG_NOTE = "❗ Izoh juda uzun (ko'pi bilan 2000 belgi)."
USE_BUTTONS = "Quyidagi tugmalardan birini bosing."
SUBMITTED = "✅ Tekshiruvga yuborildi"
SUBMIT_FAIL = "❗ Yuborib bo'lmadi."
DUE_SAVED = "✅ Muddat qo'yildi"


def _d(iso) -> str:
    s = str(iso or "")
    try:
        return f"{date.fromisoformat(s[:10]):%d.%m.%Y}"
    except ValueError:
        return s


def due_text(d: dict | str | None) -> str:
    """Date and the marks of a RoverTask: «Muddat: 15.11.2026 (avto)», late -> ⚠️."""
    t = d if isinstance(d, dict) else {}
    if not t.get("due_date"):
        return "🗓 Muddat hali belgilanmagan"
    line = f"🗓 Muddat: {esc(_d(t['due_date']))}"
    if t.get("due_auto"):
        line += " (avto)"
    if t.get("overdue"):
        line += f" ⚠️ {esc(t.get('days_late') or 0)} kun kechikdi"
    return line


def _info(t: dict) -> list[str]:
    order = t.get("order") or {}
    client = t.get("client") or {}
    lines = [f"Buyurtma №{esc(order.get('number'))}"]
    if client.get("fio"):
        lines.append(f"👤 {esc(client['fio'])}")
    if client.get("phone"):
        lines.append(f"📞 {esc(client['phone'])}")
    if t.get("address"):
        addr = f"📍 {esc(t['address'])}"
        if t.get("map_url"):
            addr += f' (<a href="{html.escape(str(t["map_url"]), quote=True)}">xarita</a>)'
        lines.append(addr)
    lines.append(f"📐 Maydon: {esc(t.get('square'))} m²")
    return lines


def _worker_info(t: dict) -> list[str]:
    """The rover worker sees only what the job needs (owner): client ID (= order number),
    the design folder, the area; no client name, phone or map."""
    order = t.get("order") or {}
    lines = [f"🆔 Mijoz ID: {esc(order.get('number'))}"]
    folder = t.get("design_folder_url")
    if folder:
        lines.append(f'📁 <a href="{html.escape(str(folder), quote=True)}">Dizayn papkasi</a>')
    else:
        lines.append("📁 Dizayn papkasi: yo'q")
    lines.append(f"📐 Maydon: {esc(t.get('square'))} m²")
    return lines


def task_card(t: dict) -> str:
    lines = [TASK_HEADER, ""] + _worker_info(t) + [due_text(t)]
    state = t.get("state")
    if state in ("checking", "done"):
        cur = t.get("currency") or "UZS"
        lines.append(f"💰 Summa: {esc(fmt_cur(t.get('amount'), cur))} {cur_name(cur)}")
        if (t.get("note") or "").strip():
            lines.append(f"📝 Izoh: {esc(t['note'])}")
        lines.append("")
        if state == "checking":
            lines.append("⏳ Tekshiruvda")
        else:
            checker = (t.get("checked_by") or {}).get("name")
            lines.append(f"✅ Tasdiqlandi — {esc(checker or '—')}")
    return "\n".join(lines)


def head_card(t: dict) -> str:
    return "\n".join([HEAD_HEADER, ""] + _info(t) + [due_text(t)])


def summary(amount: str, note: str) -> str:
    return (
        "Tekshiring:\n\n"
        f"💰 Summa: {esc(fmt_cur(amount, 'UZS'))} so'm\n"
        f"📝 Izoh: {esc(note)}\n\n"
        "Tekshiruvga yuboraymi?"
    )


def due_set_msg(t: dict, how: str | None, by_name: str | None) -> str:
    num = esc((t.get("order") or {}).get("number"))
    line = f"🗓 Rover №{num} muddati: {esc(_d(t.get('due_date')))}"
    if how == "auto":
        line += " (avtomatik)"
    elif by_name:
        line += f" ({esc(by_name)} qo'ydi)"
    return line


def remind_text(t: dict, what: str, days_late: int, head: bool = False) -> str:
    num = esc((t.get("order") or {}).get("number"))
    if head:
        return f"🔴 Rover kechikyapti ({esc(days_late)} kun) — №{num}"
    if what == "overdue":
        return f"⚠️ Rover muddati o'tdi ({esc(days_late)} kun) — №{num}"
    return f"⏰ Ertaga Rover muddati tugaydi — №{num}"
