"""Strings of the painter bot part (Uzbek). Everything from the backend is HTML-escaped."""

from __future__ import annotations

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


def m2(value) -> str:
    """10.0 -> «10», 3.5 -> «3.5», 2.345 -> «2.35»."""
    try:
        return f"{float(value):.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(esc(value))


def _num(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def remainder_of(t: dict) -> float:
    """m² of the job that no team has got yet (0 when unknown / fully assigned)."""
    total, got = _num(t.get("square")), _num(t.get("assigned_square"))
    if total is None or got is None:
        return 0.0
    left = round(total - got, 2)
    return left if left > 0 else 0.0


def _name(u) -> str:
    return str((u or {}).get("name") or "") if isinstance(u, dict) else ""


def _info(t: dict, hide_contact: bool = False) -> list[str]:
    """hide_contact: no phone (worker card of an outsource team)."""
    order = t.get("order") or {}
    client = t.get("client") or {}
    lines = [f"Buyurtma №{esc(order.get('number'))}"]
    if client.get("fio"):
        lines.append(f"👤 {esc(client['fio'])}")
    if client.get("phone") and not hide_contact:
        lines.append(f"📞 {esc(client['phone'])}")
    # no address / map on molyar task messages (owner)
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


def parts_line(parts) -> str:
    """«Autsors — 10 m², Proizvodstva — 5 m²»."""
    return ", ".join(
        f"{esc((p.get('type') or {}).get('name') or '—')} — {m2(p.get('square'))} m²"
        for p in parts
        if isinstance(p, dict)
    )


def team_chosen(t: dict) -> str:
    """The pressed / stored card once the team is picked (one team, or a split job)."""
    num = esc((t.get("order") or {}).get("number"))
    parts = [p for p in t.get("parts") or [] if isinstance(p, dict)]
    left = remainder_of(t)
    if parts and (len(parts) > 1 or left):
        text = f"🎨 Molyar — №{num}\n✅ Jamoalar: {parts_line(parts)}"
        if left:
            text += f"\n⏳ Taqsimlanmagan: {m2(left)} m²"
        return text
    first = parts[0] if parts else {}
    ptype = (t.get("type") or first.get("type") or {}).get("name")
    who = _name(t.get("painter") or first.get("painter"))
    line = f"✅ Jamoa: {esc(ptype)}" if ptype else "✅ Jamoa tanlandi"
    if who:
        line += f" ({esc(who)})"
    return f"🎨 Molyar — №{num}\n{line}"


def done_msg(t: dict, by_name: str | None = None) -> str:
    num = esc((t.get("order") or {}).get("number"))
    lines = [f"🎨 <b>Molyar tayyor</b> — №{num}"]
    parts = [p for p in t.get("parts") or [] if isinstance(p, dict)]
    if parts:
        for p in parts:
            who = _name(p.get("painter"))
            lines.append(
                f"🎨 {esc((p.get('type') or {}).get('name') or '—')} — {m2(p.get('square'))} m²"
                + (f" ({esc(who)})" if who else "")
            )
        lines.append(f"📐 Jami maydon: {esc(t.get('square'))} m²")
    else:
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


# ---- split jobs: one card per part (team)


def _part_info(p: dict, hide_contact: bool = False, head: bool = False) -> list[str]:
    order = p.get("order") or {}
    client = p.get("client") or {}
    lines = [f"Buyurtma №{esc(order.get('number'))}"]
    if client.get("fio"):
        lines.append(f"👤 {esc(client['fio'])}")
    if client.get("phone") and not hide_contact:
        lines.append(f"📞 {esc(client['phone'])}")
    # no address / map on molyar task messages (owner)
    total = p.get("total_square")
    tail = f" (jami {m2(total)} m²)" if total not in (None, "") else ""
    lines.append(f"📐 {'Qism' if head else 'Sizning qismingiz'}: {m2(p.get('square'))} m²{tail}")
    ptype = (p.get("type") or {}).get("name")
    if ptype:
        lines.append(f"🎨 {'Jamoa' if head else 'Tur'}: {esc(ptype)}")
    return lines


def part_task_card(p: dict) -> str:
    """Worker card of one part: open -> due line; done -> note + who."""
    lines = [TASK_HEADER, ""] + _part_info(p, hide_contact=bool(p.get("outsource")))
    lines.append(due_line(p))
    if p.get("state") == "done":
        lines += _done_tail(p)
    return "\n".join(lines)


def part_resized_card(p: dict) -> str:
    return part_task_card(p)


def part_reassigned_card(p: dict) -> str:
    return "\n".join([part_task_card(p), "", REASSIGNED])


def part_head_card(p: dict) -> str:
    lines = [HEAD_HEADER, ""] + _part_info(p, head=True)
    who = _name(p.get("painter"))
    if who:
        lines.append(f"👷 Molyar: {esc(who)}")
    lines.append(due_line(p))
    if p.get("state") == "done":
        lines += _done_tail(p)
    return "\n".join(lines)


def resized_msg(p: dict) -> str:
    num = esc((p.get("order") or {}).get("number"))
    return f"📐 Maydon o'zgardi: {m2(p.get('square'))} m² — №{num}"


def part_done_msg(p: dict, by_name: str | None = None) -> str:
    num = esc((p.get("order") or {}).get("number"))
    ptype = esc((p.get("type") or {}).get("name") or "—")
    line = f"🎨 Molyar qismi tayyor — №{num}: {ptype} {m2(p.get('square'))} m²"
    who = _name(p.get("done_by")) or by_name
    if who:
        line += f"\n👷 {esc(who)}"
    if (p.get("note") or "").strip():
        line += f"\n📝 Izoh: {esc(p['note'])}"
    return line


def part_due_set_msg(p: dict, how: str | None, by_name: str | None) -> str:
    num = esc((p.get("order") or {}).get("number"))
    line = f"🗓 Molyar №{num} muddati: {esc(day(p.get('due_date')))}"
    if how == "auto":
        line += " (avtomatik)"
    elif by_name:
        line += f" ({esc(by_name)} qo'ydi)"
    return line


def part_remind_text(p: dict, what: str, days_late: int, head: bool = False) -> str:
    num = esc((p.get("order") or {}).get("number"))
    ptype = esc((p.get("type") or {}).get("name") or "")
    tag = f" ({ptype})" if ptype else ""
    if head:
        return f"🔴 Molyar kechikyapti ({esc(days_late)} kun) — №{num}{tag}"
    if what == "overdue":
        return f"⚠️ Molyar muddati o'tdi ({esc(days_late)} kun) — №{num}{tag}"
    return f"⏰ Ertaga Molyar muddati tugaydi — №{num}{tag}"


def remainder_msg(t: dict, remainder) -> str:
    num = esc((t.get("order") or {}).get("number"))
    return (
        f"🎨 <b>Molyar №{num}</b>: barcha qismlar bajarildi, lekin {m2(remainder)} m² "
        "hali hech kimga berilmagan — jamoaga bering"
    )
