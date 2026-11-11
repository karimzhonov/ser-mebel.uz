"""Strings of the painter bot part (Uzbek). Everything from the backend is HTML-escaped."""

from __future__ import annotations

import html

from bot.common.due import NOTE_MAX, day, due_line
from bot.common.fmt import esc

TASK_HEADER = "🎨 <b>Yangi Molyar ishi</b>"
HEAD_HEADER = "🗓 <b>Molyar uchun muddat qo'ying</b>"
DONE_HEADER = "🎨 <b>Molyar tayyor</b>"
TEAM_OK = "✅ Tanlandi"
BUSY = "Avval boshqa amalni tugating"
CANCELLED = "Bekor qilindi."
STALE = "Bu tugma eskirgan."
ASK_NOTE = "Izoh yozing: nima ish qilindi"
BAD_NOTE = "❗ Izoh juda qisqa (kamida 3 belgi)."
LONG_NOTE = f"❗ Izoh juda uzun (ko'pi bilan {NOTE_MAX} belgi)."
USE_BUTTONS = "Quyidagi tugmalardan birini bosing."
DONE_OK = "✅ Bajarildi"
DUE_SAVED = "✅ Muddat qo'yildi"
REASSIGNED = "♻️ Bu ish boshqa molyarga o'tkazildi"


def _name(u) -> str:
    return str((u or {}).get("name") or "") if isinstance(u, dict) else ""


def _info(t: dict, hide_contact: bool = False) -> list[str]:
    """hide_contact: no phone / address / map (worker card of an outsource team)."""
    order = t.get("order") or {}
    client = t.get("client") or {}
    lines = [f"Buyurtma №{esc(order.get('number'))}"]
    if client.get("fio"):
        lines.append(f"👤 {esc(client['fio'])}")
    if client.get("phone") and not hide_contact:
        lines.append(f"📞 {esc(client['phone'])}")
    if t.get("address") and not hide_contact:
        addr = f"📍 {esc(t['address'])}"
        if t.get("map_url"):
            addr += f' (<a href="{html.escape(str(t["map_url"]), quote=True)}">xarita</a>)'
        lines.append(addr)
    lines.append(f"📐 Maydon: {esc(t.get('square'))} m²")
    ptype = (t.get("type") or {}).get("name")
    if ptype:
        lines.append(f"🎨 Tur: {esc(ptype)}")
    return lines


def _done_tail(t: dict) -> list[str]:
    lines = []
    if (t.get("note") or "").strip():
        lines.append(f"📝 Izoh: {esc(t['note'])}")
    who = _name(t.get("done_by"))
    lines += ["", f"✅ Bajarildi{' — ' + esc(who) if who else ''}"]
    return lines


def task_card(t: dict) -> str:
    """Painter's card: new -> due line; done -> note + who."""
    lines = [TASK_HEADER, ""] + _info(t, hide_contact=bool(t.get("outsource"))) + [due_line(t)]
    if t.get("state") == "done":
        lines += _done_tail(t)
    return "\n".join(lines)


def reassigned_card(t: dict) -> str:
    return "\n".join([task_card(t), "", REASSIGNED])


def head_card(t: dict) -> str:
    lines = [HEAD_HEADER, ""] + _info(t)
    who = _name(t.get("painter"))
    if who:
        lines.append(f"👷 Molyar: {esc(who)}")
    lines.append(due_line(t))
    if t.get("state") == "done":
        lines += _done_tail(t)
    return "\n".join(lines)


def summary(note: str) -> str:
    return f"Tekshiring:\n\n📝 Izoh: {esc(note)}\n\nMolyar ishi tayyor deb yuboraymi?"


def ready_msg(t: dict) -> str:
    """Head card: the rover is done, pick the team."""
    num = esc((t.get("order") or {}).get("number"))
    lines = [f"🎨 <b>Rover tayyor — №{num}: jamoani tanlang</b>", ""] + _info(t)
    return "\n".join(lines)


def team_chosen(t: dict) -> str:
    """The pressed / stored card once the team is picked."""
    num = esc((t.get("order") or {}).get("number"))
    ptype = (t.get("type") or {}).get("name")
    who = _name(t.get("painter"))
    line = f"✅ Jamoa: {esc(ptype)}" if ptype else "✅ Jamoa tanlandi"
    if who:
        line += f" ({esc(who)})"
    return f"🎨 Molyar — №{num}\n{line}"


def done_msg(t: dict, by_name: str | None = None) -> str:
    num = esc((t.get("order") or {}).get("number"))
    lines = [f"🎨 <b>Molyar tayyor</b> — №{num}"]
    who = _name(t.get("painter")) or by_name
    if who:
        lines.append(f"👷 Molyar: {esc(who)}")
    ptype = (t.get("type") or {}).get("name")
    if ptype:
        lines.append(f"🎨 Tur: {esc(ptype)}")
    lines.append(f"📐 Maydon: {esc(t.get('square'))} m²")
    if (t.get("note") or "").strip():
        lines.append(f"📝 Izoh: {esc(t['note'])}")
    return "\n".join(lines)


def due_set_msg(t: dict, how: str | None, by_name: str | None) -> str:
    num = esc((t.get("order") or {}).get("number"))
    line = f"🗓 Molyar №{num} muddati: {esc(day(t.get('due_date')))}"
    if how == "auto":
        line += " (avtomatik)"
    elif by_name:
        line += f" ({esc(by_name)} qo'ydi)"
    return line


def remind_text(t: dict, what: str, days_late: int, head: bool = False) -> str:
    num = esc((t.get("order") or {}).get("number"))
    if head:
        return f"🔴 Molyar kechikyapti ({esc(days_late)} kun) — №{num}"
    if what == "overdue":
        return f"⚠️ Molyar muddati o'tdi ({esc(days_late)} kun) — №{num}"
    return f"⏰ Ertaga Molyar muddati tugaydi — №{num}"
