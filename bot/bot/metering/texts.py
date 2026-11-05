"""All strings of the zamer (metering) bot part (Uzbek). `callback_data` strings live in
keyboards.py and must stay stable. Everything coming from the backend is HTML-escaped."""

from __future__ import annotations

from datetime import datetime
from html import escape

from bot.common.fmt import esc

OPEN_STATUSES = ("created", "other_day")

HEADERS = {
    "assigned": "📏 <b>Sizga yangi zamer</b>",
    "reassigned": "📏 <b>Zamer sizga o'tkazildi</b>",
    "soon": "⏰ <b>1 soatdan keyin zamer</b>",
    "late": "⚠️ <b>Zamer vaqti o'tdi — natijani belgilang</b>",
    "moved": "🕒 <b>Zamer vaqti o'zgardi</b>",
    "plain": "📏 <b>Zamer</b>",
}
# plain text of the headers (what `Message.text` shows) -> card kind
_KIND_BY_PLAIN = {
    "📏 Sizga yangi zamer": "assigned",
    "📏 Zamer sizga o'tkazildi": "reassigned",
    "🕒 Zamer vaqti o'zgardi": "moved",
    "⏰ 1 soatdan keyin zamer": "soon",
    "⚠️ Zamer vaqti o'tdi — natijani belgilang": "late",
}

WEEKDAYS = (
    "Dushanba",
    "Seshanba",
    "Chorshanba",
    "Payshanba",
    "Juma",
    "Shanba",
    "Yakshanba",
)

CONFIRM_ASK = "❓ O'lchov olinganini tasdiqlaysizmi?"
PICK_TIME = "Yangi vaqtni tanlang"
ASK_TIME = (
    "🕒 Yangi vaqtni yozing: <code>14:30</code> (bugun), <code>25.12</code> yoki "
    "<code>25.12 14:30</code>.\n(Mijoz bilan kelishib oling.)"
)
ASK_REASON = "❌ Sababini yozing (nega zamer bo'lmadi?):"
CANCELLED = "Bekor qilindi."
STALE = "Bu tugma eskirgan."
BUSY = "Hozir boshqa amal ochiq. Uni tugating yoki /bekor ni bosing."
SAVED_OK = "✅ Saqlandi"
UPLOAD_LINE = "📤 Fayllarni saytga yuklang"
DIGEST_MAX = 3800  # a Telegram message is 4096 chars; leave room for the header


def kind_of(text: str | None) -> str:
    """Card kind recovered from the first line of a card message (plain text)."""
    first = (text or "").strip().split("\n", 1)[0].strip()
    return _KIND_BY_PLAIN.get(first, "assigned")


def _dt(iso) -> datetime | None:
    s = str(iso or "")
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def when(iso) -> str:
    """'2026-12-25T14:30:00' -> '25.12 (Payshanba) 14:30'."""
    d = _dt(iso)
    if d is None:
        return str(iso) if iso else "—"
    return f"{d:%d.%m} ({WEEKDAYS[d.weekday()]}) {d:%H:%M}"


def dt_short(iso) -> str:
    d = _dt(iso)
    return f"{d:%d.%m %H:%M}" if d else (str(iso) if iso else "—")


def step_label(step: str | None) -> str:
    return {"design_price": "dizayn + narx", "price": "narx"}.get(step or "", "")


def _name(ref) -> str:
    return str((ref or {}).get("name") or "") if isinstance(ref, dict) else ""


def status_line(m: dict, *, how: str | None = None, to_name: str | None = None) -> str:
    st = m.get("status")
    if how == "reassigned":
        return f"↪️ {esc(to_name or _name(m.get('measurer')) or '—')} ga o'tkazildi"
    if st == "metering_done":
        return UPLOAD_LINE
    if st == "done":
        step = step_label(m.get("next_step"))
        tail = f"{step} tayinlandi" if step else "tayinlandi"
        return f"✅ Bajarildi — fayllar yuklandi, {tail}"
    if st == "dont_need":
        reason = esc(m.get("cancel_reason") or "")
        return f"❌ Bekor bo'ldi: {reason}" if reason else "❌ Bekor bo'ldi"
    return ""


def card(m: dict, kind: str = "assigned", *, how: str | None = None, to_name=None) -> str:
    """The zamer card. The header follows the kind while the zamer is open; a finished /
    handed-over one gets the neutral header (its status line says the rest)."""
    st = m.get("status")
    if how == "reassigned" or st not in OPEN_STATUSES:
        head = HEADERS["plain"]
    elif how == "rescheduled":
        head = HEADERS["moved"]
    else:
        head = HEADERS.get(kind, HEADERS["assigned"])
    cl = m.get("client") or {}
    rows = [head, ""]
    rows.append(f"👤 {esc(cl.get('fio') or '—')}")
    if cl.get("phone"):
        rows.append(f"📞 {esc(cl['phone'])}")
    if m.get("address"):
        rows.append(f"📍 {esc(m['address'])}")
    rows.append(f"🗓 {esc(when(m.get('date_time')))}")
    if m.get("desc"):
        rows.append(f"📝 {esc(m['desc'])}")
    if _name(m.get("operator")):
        rows.append(f"🧑‍💼 {esc(_name(m['operator']))}")
    line = status_line(m, how=how, to_name=to_name)
    if line:
        rows += ["", line]
    return "\n".join(rows)


def moved_watch(m: dict, by_name: str) -> str:
    """To the operator when the measurer moved the zamer."""
    fio = (m.get("client") or {}).get("fio") or "—"
    return (
        f"🕒 Zamer ko'chirildi: {esc(fio)} → {esc(dt_short(m.get('date_time')))} ({esc(by_name)})"
    )


def _digest_line(m: dict) -> str:
    cl = m.get("client") or {}
    d = _dt(m.get("date_time"))
    hhmm = f"{d:%H:%M}" if d else "—"
    parts = [esc(cl.get("fio") or "—")]
    if cl.get("phone"):
        parts.append(esc(cl["phone"]))
    addr = m.get("address") or ""
    if addr:
        url = m.get("map_url") or ""
        parts.append(f'<a href="{escape(url, quote=True)}">{esc(addr)}</a>' if url else esc(addr))
    return f"{hhmm} — " + ", ".join(parts)


def digest_pages(items: list[dict]) -> list[str]:
    """«🗓 Ertangi zamerlar (n)» split into messages under the Telegram limit."""
    head = f"🗓 <b>Ertangi zamerlar ({len(items)})</b>"
    pages: list[str] = []
    cur = head
    for m in items:
        line = _digest_line(m)
        if len(cur) + len(line) + 2 > DIGEST_MAX and cur != head:
            pages.append(cur)
            cur = f"{head} (davomi)"
        cur += "\n\n" + line
    pages.append(cur)
    return pages
