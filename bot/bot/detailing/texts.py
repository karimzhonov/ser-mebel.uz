"""Strings of the detailing bot part (Uzbek). Everything from the backend is HTML-escaped."""

from __future__ import annotations

import html
from datetime import date, datetime

from bot.common.fmt import esc

NEW_HEADER = "📐 <b>Yangi detalirovka</b>"
MOVED_HEADER = "🗓 <b>Detalirovka muddati o'zgardi</b>"
DONE_HINT = "Tayyor bo'lgach «✅ Bajardim» ni bosing — saytda maydon va usluga'ni kiritasiz."


def _dt(iso) -> str:
    s = str(iso or "")
    try:
        return f"{datetime.fromisoformat(s.replace('Z', '+00:00')):%d.%m.%Y %H:%M}"
    except ValueError:
        return s


def _d(iso) -> str:
    s = str(iso or "")
    try:
        return f"{date.fromisoformat(s[:10]):%d.%m.%Y}"
    except ValueError:
        return s


def task_card(t: dict, how: str | None = "new") -> str:
    """Card from a DetailingTask DTO: order, client, address, the detailing deadline."""
    order = t.get("order") or {}
    client = t.get("client") or {}
    header = MOVED_HEADER if how == "moved" else NEW_HEADER
    lines = [header, "", f"Buyurtma №{esc(order.get('number'))}"]
    if client.get("fio"):
        lines.append(f"👤 {esc(client['fio'])}")
    if client.get("phone"):
        lines.append(f"📞 {esc(client['phone'])}")
    address = (t.get("address") or "").strip()
    map_url = t.get("map_url")
    if address and map_url:
        lines.append(f'📍 <a href="{html.escape(str(map_url), quote=True)}">{esc(address)}</a>')
    elif address:
        lines.append(f"📍 {esc(address)}")
    elif map_url:
        lines.append(f'📍 <a href="{html.escape(str(map_url), quote=True)}">Xarita</a>')
    if t.get("end_date"):
        lines.append(f"📅 Topshirish sanasi: {esc(_d(t['end_date']))}")
    lines.append("")
    if t.get("due_at"):
        lines.append(f"⏰ <b>Detalirovka muddati: {esc(_dt(t['due_at']))}</b>")
    else:
        lines.append("⏰ Detalirovka muddati belgilanmagan")
    if t.get("done"):
        lines.append("✅ Bajarilgan")
    else:
        lines.append(DONE_HINT)
    return "\n".join(lines)
