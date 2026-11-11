"""Inline keyboards of the painter cards. callback_data (stable):
painter: pn:dn:{id} («✅ Bajardim», only while the task is new; asks the izoh),
pn:sy:{id} («✅ Yuborish»), pn:se:{id} («✏️ Qaytadan»), pn:q («❌ Bekor qilish»).
production head: pn:dd:{days}:{id} («+5 kun» / «+10 kun» / «+14 kun»)."""

from __future__ import annotations

from bot.common.kb import b, ik, url_button

OPEN_PANEL = "🌐 Saytda ochish"
PRESETS = (5, 10, 14)


def _site(url: str) -> list:
    return [url_button(OPEN_PANEL, url)] if url else []


def task_kb(pid: int, state: str, url: str = ""):
    """Painter card: «✅ Bajardim» only while the task is new."""
    rows = []
    if state == "new":
        rows.append([b("✅ Bajardim", f"pn:dn:{pid}")])
    rows.append(_site(url))
    return ik(rows) or None


def link_kb(url: str = ""):
    return ik([_site(url)]) or None


def due_kb(pid: int, presets=PRESETS, url: str = "", state: str = "new"):
    """Head card: deadline presets (not for a done task) + site link."""
    rows = []
    if state != "done":
        rows.append([b(f"+{d} kun", f"pn:dd:{int(d)}:{pid}") for d in presets or PRESETS])
    rows.append(_site(url))
    return ik(rows) or None


def cancel_kb():
    return ik([[b("❌ Bekor qilish", "pn:q")]])


def summary_kb(pid: int):
    return ik(
        [
            [b("✅ Yuborish", f"pn:sy:{pid}")],
            [b("✏️ Qaytadan", f"pn:se:{pid}")],
            [b("❌ Bekor qilish", "pn:q")],
        ]
    )
