"""Small helpers shared by the deadline cards (used by the painter part; rover keeps its own
copies): date formatting, the «Muddat» line, the izoh length check."""

from __future__ import annotations

from datetime import date

from bot.common.fmt import esc

NOTE_MIN = 3
NOTE_MAX = 2000


def day(iso) -> str:
    """«2026-11-15» -> «15.11.2026» (anything unparsable is returned as is)."""
    s = str(iso or "")
    try:
        return f"{date.fromisoformat(s[:10]):%d.%m.%Y}"
    except ValueError:
        return s


def due_line(t: dict | None) -> str:
    """«Muddat: 15.11.2026 (avto) ⚠️ 2 kun kechikdi» of a task DTO (HTML-safe)."""
    t = t if isinstance(t, dict) else {}
    if not t.get("due_date"):
        return "🗓 Muddat hali belgilanmagan"
    line = f"🗓 Muddat: {esc(day(t['due_date']))}"
    if t.get("due_auto"):
        line += " (avto)"
    if t.get("overdue"):
        line += f" ⚠️ {esc(t.get('days_late') or 0)} kun kechikdi"
    return line


def note_ok(text) -> bool:
    return NOTE_MIN <= len(str(text or "").strip()) <= NOTE_MAX
