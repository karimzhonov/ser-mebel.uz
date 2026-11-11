"""Inline keyboards of the painter cards. callback_data (stable):
painter: pn:dn:{id} («✅ Bajardim», only while the task is new; asks the izoh),
pn:sy:{id} («✅ Yuborish»), pn:se:{id} («✏️ Qaytadan»), pn:q («❌ Bekor qilish»).
production head: pn:dd:{days}:{id} («+5 kun» / «+10 kun» / «+14 kun»),
pn:ty:{type_id}:{id} (pick the painter team after the rover)."""

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


LABEL_MAX = 40


def team_kb(pid: int, types, url: str = ""):
    """Head card after the rover: one button per team (`pn:ty:{type_id}:{id}`) + site link."""
    rows = []
    for t in types or []:
        try:
            tid = int(t["id"])
        except (KeyError, TypeError, ValueError):
            continue
        label = str(t.get("name") or tid)
        who = str((t.get("user") or {}).get("name") or "")
        if who and len(label) + 3 + len(who) <= LABEL_MAX:
            label += f" · {who}"
        rows.append([b(label, f"pn:ty:{tid}:{int(pid)}")])
    rows.append(_site(url))
    return ik(rows) or None
