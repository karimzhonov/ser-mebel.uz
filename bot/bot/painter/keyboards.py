"""Inline keyboards of the painter cards. callback_data (stable):
painter: pn:dn:{id} («✅ Bajardim», only while the task is new; asks the izoh),
pn:sy:{id} («✅ Yuborish»), pn:se:{id} («✏️ Qaytadan»), pn:q («❌ Bekor qilish»).
production head: pn:dd:{days}:{id} («+5 kun» / «+10 kun» / «+14 kun»),
pn:ty:{type_id}:{id} (pick the painter team after the rover; whole job to one team).
Split job parts (id = PART id): pn:pd:{part} («✅ Bajardim»), pn:psy:{part} / pn:pse:{part}
(«Yuborish» / «Qaytadan»), pn:pdd:{days}:{part} (deadline preset). «✂️ Bo'lib berish (saytda)»
is a URL button (the split is edited on the site only)."""

from __future__ import annotations

from bot.common.kb import b, ik, url_button

OPEN_PANEL = "🌐 Saytda ochish"
PRESETS = (5, 10, 14)
SPLIT_BTN = "✂️ Bo'lib berish (saytda)"


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


def part_task_kb(part_id: int, state: str, url: str = ""):
    """Worker card of one part: «✅ Bajardim» (`pn:pd:{part}`) only while it is open."""
    rows = []
    if state == "new":
        rows.append([b("✅ Bajardim", f"pn:pd:{part_id}")])
    rows.append(_site(url))
    return ik(rows) or None


def part_due_kb(part_id: int, presets=PRESETS, url: str = "", state: str = "new"):
    """Head card of one part: deadline presets (`pn:pdd:{days}:{part}`) + site link."""
    rows = []
    if state != "done":
        rows.append([b(f"+{d} kun", f"pn:pdd:{int(d)}:{part_id}") for d in presets or PRESETS])
    rows.append(_site(url))
    return ik(rows) or None


def split_kb(split_url: str = "", url: str = ""):
    """Link row(s) to the split editor on the site (+ the plain site link)."""
    rows = []
    if split_url:
        rows.append([url_button(SPLIT_BTN, split_url)])
    rows.append(_site(url))
    return ik(rows) or None


def summary_kb(pid: int, kind: str = "job"):
    """kind «job»: `pn:sy|se:{painter}`; kind «part»: `pn:psy|pse:{part}`."""
    sy, se = ("pn:psy", "pn:pse") if kind == "part" else ("pn:sy", "pn:se")
    return ik(
        [
            [b("✅ Yuborish", f"{sy}:{pid}")],
            [b("✏️ Qaytadan", f"{se}:{pid}")],
            [b("❌ Bekor qilish", "pn:q")],
        ]
    )


LABEL_MAX = 40


def team_kb(pid: int, types, url: str = "", split_url: str = ""):
    """Head card after the rover: one button per team (`pn:ty:{type_id}:{id}`, whole job),
    the «✂️ Bo'lib berish (saytda)» URL button (when `split_url`) and the site link."""
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
    if split_url:
        rows.append([url_button(SPLIT_BTN, split_url)])
    rows.append(_site(url))
    return ik(rows) or None
