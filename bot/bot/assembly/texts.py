"""Strings of the assembly bot part (Uzbek). Everything from the backend is HTML-escaped."""

from __future__ import annotations

import html

from bot.common.due import NOTE_MAX, day, due_line
from bot.common.fmt import esc

TASK_HEADER = "🔧 <b>Yangi Yig'ish/O'rnatish ishi</b>"
HEAD_HEADER = "🗓 <b>Yig'ish uchun muddat qo'ying</b>"
TEAM_OK = "✅ Tanlandi"
BUSY = "Avval boshqa amalni tugating"
CANCELLED = "Bekor qilindi."
STALE = "Bu tugma eskirgan."
ASK_NOTE = "Izoh yozing: nima ish qilindi (yig'ish va o'rnatish)"
BAD_NOTE = "❗ Izoh juda qisqa (kamida 3 belgi)."
LONG_NOTE = f"❗ Izoh juda uzun (ko'pi bilan {NOTE_MAX} belgi)."
USE_BUTTONS = "Quyidagi tugmalardan birini bosing."
DONE_OK = "✅ O'rnatildi"
CHECKING_LINE = "⏳ Tekshiruvda — rahbar tasdiqlashi kutilmoqda"
CONFIRM_ASK = "Tasdiqlaysizmi? Buyurtma Готов bo'ladi"
CONFIRM_OK = "✅ Tayyor"
DUE_SAVED = "✅ Muddat qo'yildi"
REASSIGNED = "♻️ Bu ish boshqa yig'uvchiga o'tkazildi"
NO_ASSEMBLERS = "Yig'uvchilar yo'q — saytda tanlang"


def _name(u) -> str:
    return str((u or {}).get("name") or "") if isinstance(u, dict) else ""


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


def _done_tail(t: dict) -> list[str]:
    lines = []
    if (t.get("note") or "").strip():
        lines.append(f"📝 Izoh: {esc(t['note'])}")
    who = _name(t.get("finished_by"))
    lines += ["", f"✅ O'rnatildi{' — ' + esc(who) if who else ''}"]
    return lines


def _state_lines(t: dict) -> list[str]:
    lines = []
    if t.get("state") == "assembled":
        lines.append("Holat: Yig'ildi — o'rnatish qoldi")
    if t.get("state") == "checking":
        lines += _done_tail(t) + [CHECKING_LINE]
    if t.get("state") == "done":
        lines += _done_tail(t)
        who = _name(t.get("confirmed_by"))
        if who:
            lines.append(f"✅ Tayyor — {esc(who)} tasdiqladi")
    return lines


def task_card(t: dict) -> str:
    """Assembler's card: due line; assembled -> remaining; done -> note + who."""
    lines = [TASK_HEADER, ""] + _info(t) + [due_line(t)]
    return "\n".join(lines + _state_lines(t))


def reassigned_card(t: dict) -> str:
    return "\n".join([task_card(t), "", REASSIGNED])


def head_card(t: dict) -> str:
    lines = [HEAD_HEADER, ""] + _info(t)
    who = _name(t.get("assembler"))
    if who:
        lines.append(f"👷 Yig'uvchi: {esc(who)}")
    lines.append(due_line(t))
    return "\n".join(lines + _state_lines(t))


def summary(note: str) -> str:
    return f"Tekshiring:\n\n📝 Izoh: {esc(note)}\n\nYig'ish va o'rnatish tayyor deb yuboraymi?"


def ready_msg(t: dict, has_assemblers: bool = True) -> str:
    """Head card: the job went to assembly, pick the team."""
    num = esc((t.get("order") or {}).get("number"))
    lines = [f"🔧 <b>Yig'ishga tushdi — №{num}: jamoani tanlang</b>", ""] + _info(t)
    who = _name(t.get("assembler"))
    if who:
        lines.append(f"👷 Yig'uvchi: {esc(who)}")
    if not has_assemblers:
        lines += ["", NO_ASSEMBLERS]
    return "\n".join(lines)


def team_chosen(t: dict) -> str:
    """The pressed / stored card once the team is picked."""
    num = esc((t.get("order") or {}).get("number"))
    who = _name(t.get("assembler"))
    line = f"✅ Jamoa: {esc(who)}" if who else "✅ Jamoa tanlandi"
    return f"🔧 Yig'ish — №{num}\n{line}"


def done_msg(t: dict, by_name: str | None = None) -> str:
    num = esc((t.get("order") or {}).get("number"))
    lines = [f"🔧 <b>O'rnatib bo'lishdi</b> — №{num}"]
    who = _name(t.get("assembler")) or _name(t.get("finished_by")) or by_name
    if who:
        lines.append(f"👷 Yig'uvchi: {esc(who)}")
    lines.append(f"📐 Maydon: {esc(t.get('square'))} m²")
    if (t.get("note") or "").strip():
        lines.append(f"📝 Izoh: {esc(t['note'])}")
    if by_name and by_name != who:
        # someone other than the assembler (a manager on the site) closed it
        lines.append(f"✅ Belgiladi: {esc(by_name)}")
    return "\n".join(lines)


def due_set_msg(t: dict, how: str | None, by_name: str | None) -> str:
    num = esc((t.get("order") or {}).get("number"))
    line = f"🗓 Yig'ish №{num} muddati: {esc(day(t.get('due_date')))}"
    if how == "auto":
        line += " (avtomatik)"
    elif by_name:
        line += f" ({esc(by_name)} qo'ydi)"
    return line


def remind_text(t: dict, what: str, days_late: int, head: bool = False) -> str:
    num = esc((t.get("order") or {}).get("number"))
    if head:
        return f"🔴 Yig'ish kechikyapti ({esc(days_late)} kun) — №{num}"
    if what == "overdue":
        return f"⚠️ Yig'ish muddati o'tdi ({esc(days_late)} kun) — №{num}"
    return f"⏰ Ertaga Yig'ish muddati tugaydi — №{num}"


def confirmed_msg(t: dict, by_name: str | None = None) -> str:
    """The head's «installed» message once somebody confirmed (link only)."""
    num = esc((t.get("order") or {}).get("number"))
    who = by_name or _name(t.get("confirmed_by"))
    return f"✅ <b>Tayyor</b> — №{num}" + (f" ({esc(who)} tasdiqladi)" if who else "")


def order_ready_msg(t: dict) -> str:
    num = esc((t.get("order") or {}).get("number"))
    return f"✅ Buyurtma №{num} tayyor"
