"""All strings of the design / price bot part (Uzbek). `callback_data` strings live in
keyboards.py and must stay stable. Everything coming from the backend is HTML-escaped.

`task` is the backend's OfferTask (docs/BOT_CONTRACT.md): kind design|price, id, rev,
round, stage, client{fio, phone}, address, due_at, assignee, manager, measurer, note,
last_comment, url, present_url."""

from __future__ import annotations

import re
from datetime import date

from bot.common import fmt
from bot.common.fmt import esc
from bot.metering.texts import _dt, dt_short, when

NAME = {"design": "dizayn", "price": "narx"}
CODE = {"design": "d", "price": "p"}

# card kinds of the assignee's card -> header (design, price)
HEADERS = {
    "new": ("🎨 <b>Sizga yangi dizayn</b>", "🧮 <b>Sizga narx hisoblash</b>"),
    "reassigned": (
        "↪️ <b>Dizayn sizga o'tkazildi</b>",
        "↪️ <b>Narx hisoblash sizga o'tkazildi</b>",
    ),
    "changes": (
        "✏️ <b>Mijoz o'zgartirish so'radi ({n}-raund)</b>",
        "✏️ <b>Mijoz qayta hisoblashni so'radi ({n}-raund)</b>",
    ),
    "started": (
        "🧮 <b>Dizayn tasdiqlandi — narxni hisoblang</b>",
        "🧮 <b>Dizayn tasdiqlandi — narxni hisoblang</b>",
    ),
    "soon": ("⏰ <b>Ertaga muddat</b>", "⏰ <b>Ertaga muddat</b>"),
    "today": ("⏰ <b>Bugun muddat</b>", "⏰ <b>Bugun muddat</b>"),
    "late": ("⚠️ <b>Muddat o'tdi</b>", "⚠️ <b>Muddat o'tdi</b>"),
    "overdue": ("⚠️ <b>Muddat o'tib ketdi</b>", "⚠️ <b>Muddat o'tib ketdi</b>"),
    "plain": ("🎨 <b>Dizayn</b>", "🧮 <b>Narx hisoblash</b>"),
}
PRESENT_HEADERS = {
    "ready": (
        "🎨 <b>Dizayn tayyor — mijozga ko'rsating</b>",
        "🧮 <b>Narx tayyor — mijozga ko'rsating</b>",
    ),
    "reminder": (
        "⏰ <b>Mijoz javobi kutilmoqda: dizayn</b>",
        "⏰ <b>Mijoz javobi kutilmoqda: narx</b>",
    ),
    "plain": ("🎨 <b>Dizayn</b>", "🧮 <b>Narx</b>"),
}

# plain first line of a work card (what `Message.text` shows) -> card kind
_PLAIN_KINDS = {
    re.sub(r"<[^>]+>", "", h.replace("{n}", "N")): kind for kind, hs in HEADERS.items() for h in hs
}
_ROUND_RE = re.compile(r"\(\d+-raund\)")

CONFIRM_ASK = "❓ Mijoz javobini tasdiqlaysizmi?"
PICK_TIME = "Yangi muddatni tanlang"
ASK_TIME = (
    "🕒 Yangi muddatni yozing: <code>18:00</code> (bugun), <code>25.12</code> yoki "
    "<code>25.12 18:00</code>."
)
ASK_COMMENT = {
    "d": "✏️ Nima o'zgarishi kerak? Yozing (dizaynerga yuboriladi):",
    "p": "🔁 Nimani qayta hisoblash kerak? Yozing (hisoblovchiga yuboriladi):",
}
ASK_REASON = {
    "d": "❌ Mijoz nega dizaynni rad etdi? Sababini yozing:",
    "p": "❌ Narx nega qoniqtirmadi? Sababini yozing:",
}
CANCELLED = "Bekor qilindi."
STALE = "Bu tugma eskirgan."
BUSY = "Hozir boshqa amal ochiq. Uni tugating yoki /bekor ni bosing."
SAVED_OK = "✅ Saqlandi"
SITE_HINT = "Tayyor bo'lsa saytda «Tayyor»ni bosing"
NO_DUE = "Muddat yo'q"


def kind_of(text: str | None) -> str:
    """Card kind recovered from the first line of an assignee card (plain text)."""
    first = _ROUND_RE.sub("(N-raund)", (text or "").strip().split("\n", 1)[0].strip())
    return _PLAIN_KINDS.get(first, "new")


def _name(ref) -> str:
    return str((ref or {}).get("name") or "") if isinstance(ref, dict) else ""


def key_of(task: dict) -> str:
    """Redis key / callback id of a task: `d12` / `p12`."""
    return f"{CODE.get(task.get('kind'), 'd')}{int(task['id'])}"


def _idx(task: dict) -> int:
    return 1 if task.get("kind") == "price" else 0


def _client_rows(task: dict) -> list[str]:
    cl = task.get("client") or {}
    rows = [f"👤 {esc(cl.get('fio') or '—')}"]
    if cl.get("phone"):
        rows.append(f"📞 {esc(cl['phone'])}")
    if task.get("address"):
        rows.append(f"📍 {esc(task['address'])}")
    return rows


def due_line(task: dict) -> str:
    return f"⏳ {esc(when(task['due_at']))}" if task.get("due_at") else f"⏳ {NO_DUE}"


def work_header(task: dict, kind: str, today: date | None = None) -> str:
    if kind == "soon":
        d = _dt(task.get("due_at"))
        if d is not None and d.date() == (today or fmt.now().date()):
            kind = "today"
    head = HEADERS.get(kind, HEADERS["new"])[_idx(task)]
    return head.replace("{n}", str(int(task.get("round") or 1)))


def work_card(
    task: dict,
    kind: str = "new",
    *,
    final: str | None = None,
    comment: str | None = None,
    today: date | None = None,
) -> str:
    """The designer's / pricer's card. A finished one (`final` set) gets the neutral
    header and the status line instead of the hint."""
    head = HEADERS["plain"][_idx(task)] if final else work_header(task, kind, today)
    rows = [head, ""] + _client_rows(task)
    if comment is None and kind == "changes":
        comment = task.get("last_comment")
    if comment:
        rows.append(f"💬 {esc(comment)}")
    me = _name(task.get("measurer"))
    note = task.get("note") or ""
    if me or note:
        rows.append("📏 " + esc(me) + (": " if me and note else "") + esc(note))
    rows.append(due_line(task))
    if _name(task.get("manager")):
        rows.append(f"🧑‍💼 {esc(_name(task['manager']))}")
    rows += ["", final if final else SITE_HINT]
    return "\n".join(rows)


def present_card(
    task: dict, kind: str = "ready", *, final: str | None = None, rnd: bool = True
) -> str:
    head = (
        PRESENT_HEADERS["plain"] if final else PRESENT_HEADERS.get(kind, PRESENT_HEADERS["ready"])
    )[_idx(task)]
    rows = [head, ""] + _client_rows(task)
    if rnd and int(task.get("round") or 1) > 1:
        rows.append(f"🔄 {int(task['round'])}-raund")
    if _name(task.get("assignee")):
        label = "🎨" if task.get("kind") == "design" else "🧮"
        rows.append(f"{label} {esc(_name(task['assignee']))}")
    if final:
        rows += ["", final]
    return "\n".join(rows)


def final_line(role: str, how: str, task: dict, *, answer=None, to_name=None) -> str:
    """The status line of a finished card."""
    if how == "reassigned":
        return f"↪️ {esc(to_name or _name(task.get('assignee')) or '—')} ga o'tkazildi"
    if how == "cancelled":
        reason = esc(task.get("last_comment") or "")
        return f"❌ Bekor qilindi: {reason}" if reason else "❌ Bekor qilindi"
    if how == "done" and role == "work":
        return "✅ Tayyor — menejerga yuborildi"
    if how == "answered":
        if answer == "approved":
            return "✅ Mijoz tasdiqladi" if task.get("kind") == "design" else "✅ Mijoz rozi"
        if answer in ("changes", "recalc"):
            return "✏️ Qayta ishlashga qaytdi"
        if answer == "declined":
            reason = esc(task.get("last_comment") or "")
            return f"❌ Rad etildi: {reason}" if reason else "❌ Rad etildi"
    return ""


def moved_watch(task: dict, by_name: str) -> str:
    """To the manager when somebody else moved the deadline."""
    fio = (task.get("client") or {}).get("fio") or "—"
    return (
        f"🕒 Muddat ko'chirildi: {esc(fio)} → {esc(dt_short(task.get('due_at')))} ({esc(by_name)})"
    )


def order_ready(task: dict) -> str:
    fio = (task.get("client") or {}).get("fio") or "—"
    return f"🛒 <b>{esc(fio)}</b> narxga rozi — buyurtma rasmiylashtiring"
