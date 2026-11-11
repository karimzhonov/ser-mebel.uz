"""Inline keyboards of the rover cards. callback_data (stable):
checker: rv:ok:{id} («✅ Bajarildi», asks to confirm), rv:oky:{id} (confirmed),
rv:bk:{id} (back to the card keyboard).
worker: rv:dn:{id} («✅ Bajardim», only while the task is new; asks amount + izoh),
rv:sy:{id} («✅ Yuborish»), rv:se:{id} («✏️ Qaytadan», restart at the amount),
rv:q («❌ Bekor qilish»).
production head: rv:dd:{days}:{id} («+3 kun» / «+5 kun» / «+7 kun»)."""

from __future__ import annotations

from bot.common.kb import b, ik, url_button

OPEN_PANEL = "🌐 Saytda ochish"


def _site(url: str) -> list:
    return [url_button(OPEN_PANEL, url)] if url else []


def card_kb(rid: int, state: str, url: str = ""):
    """Action button only while the task is being checked; a done card has the link only."""
    rows = []
    if state == "checking":
        rows.append([b("✅ Bajarildi", f"rv:ok:{rid}")])
    rows.append(_site(url))
    return ik(rows) or None


def confirm_kb(rid: int, url: str = ""):
    return ik(
        [
            [b("✅ Ha, tasdiqlayman", f"rv:oky:{rid}")],
            [b("↩️ Orqaga", f"rv:bk:{rid}")],
            _site(url),
        ]
    )


PRESETS = (3, 5, 7)


def task_kb(rid: int, state: str, url: str = ""):
    """Worker card: «✅ Bajardim» only while the task is new."""
    rows = []
    if state == "new":
        rows.append([b("✅ Bajardim", f"rv:dn:{rid}")])
    rows.append(_site(url))
    return ik(rows) or None


def due_kb(rid: int, presets=PRESETS, url: str = "", state: str = "new"):
    """Head card: deadline presets (not for a done task) + site link."""
    rows = []
    if state != "done":
        rows.append([b(f"+{d} kun", f"rv:dd:{int(d)}:{rid}") for d in presets or PRESETS])
    rows.append(_site(url))
    return ik(rows) or None


def cancel_kb():
    return ik([[b("❌ Bekor qilish", "rv:q")]])


def summary_kb(rid: int):
    return ik(
        [
            [b("✅ Yuborish", f"rv:sy:{rid}")],
            [b("✏️ Qaytadan", f"rv:se:{rid}")],
            [b("❌ Bekor qilish", "rv:q")],
        ]
    )
