"""Strings of the rover bot part (Uzbek). Everything from the backend is HTML-escaped."""

from __future__ import annotations

from datetime import datetime

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
    if t.get("state") == "done":
        checker = (t.get("checked_by") or {}).get("name") or by_name
        lines.append("")
        lines.append(f"✅ Tasdiqlandi — {esc(checker or '—')}")
    return "\n".join(lines)
