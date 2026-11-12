"""Inline keyboards of the assembly cards. callback_data (stable):
assembler: as:fn:{id} («✅ O'rnatildi», while the job is not finished; asks the izoh),
as:sy:{id} («✅ Yuborish»), as:se:{id} («✏️ Qaytadan»), as:q («❌ Bekor qilish»).
production head: as:dd:{days}:{id} («+5 kun» / «+10 kun» / «+14 kun»),
as:us:{user_id}:{id} (pick the assembler / team),
as:ok:{id} («✅ Tayyor», asks to confirm), as:oky:{id} (confirmed), as:bk:{id} (back)."""

from __future__ import annotations

from bot.common.kb import b, ik, url_button

OPEN_PANEL = "🌐 Saytda ochish"
PRESETS = (5, 10, 14)
LABEL_MAX = 40


def _site(url: str) -> list:
    return [url_button(OPEN_PANEL, url)] if url else []


def task_kb(aid: int, state: str, url: str = ""):
    """Assembler card: «✅ O'rnatildi» while the job is new / assembled."""
    rows = []
    if state in ("new", "assembled"):
        rows.append([b("✅ O'rnatildi", f"as:fn:{aid}")])
    rows.append(_site(url))
    return ik(rows) or None


def confirm_card_kb(aid: int, url: str = ""):
    """Head's «installed» message: «✅ Tayyor» (asks to confirm) + site link."""
    return ik([[b("✅ Tayyor", f"as:ok:{aid}")], _site(url)])


def confirm_kb(aid: int, url: str = ""):
    return ik(
        [
            [b("✅ Ha, tayyor", f"as:oky:{aid}")],
            [b("↩️ Orqaga", f"as:bk:{aid}")],
            _site(url),
        ]
    )


def link_kb(url: str = ""):
    return ik([_site(url)]) or None


def due_kb(aid: int, presets=PRESETS, url: str = "", state: str = "new"):
    """Head card: deadline presets (not for a done job) + site link."""
    rows = []
    if state not in ("done", "checking"):
        rows.append([b(f"+{d} kun", f"as:dd:{int(d)}:{aid}") for d in presets or PRESETS])
    rows.append(_site(url))
    return ik(rows) or None


def cancel_kb():
    return ik([[b("❌ Bekor qilish", "as:q")]])


def summary_kb(aid: int):
    return ik(
        [
            [b("✅ Yuborish", f"as:sy:{aid}")],
            [b("✏️ Qaytadan", f"as:se:{aid}")],
            [b("❌ Bekor qilish", "as:q")],
        ]
    )


def team_kb(aid: int, assemblers, url: str = ""):
    """Head card: one button per assembler (`as:us:{user_id}:{id}`) + site link."""
    rows = []
    for u in assemblers or []:
        try:
            uid = int(u["id"])
        except (KeyError, TypeError, ValueError):
            continue
        label = str(u.get("name") or uid)[:LABEL_MAX]
        rows.append([b(label, f"as:us:{uid}:{int(aid)}")])
    rows.append(_site(url))
    return ik(rows) or None
