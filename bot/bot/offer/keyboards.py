"""Inline keyboards of the design / price cards. `k` is the kind code: d (design) | p (price).
callback_data (stable):
of:dm:{k}:{id} (assignee: deadline menu), of:dp:{1d|2d|3d}:{k}:{id} (preset),
of:dc:{k}:{id} (typed deadline), of:bw:{k}:{id} (back to the assignee keyboard),
of:ok:{k}:{id} (manager: asks «Tasdiqladi / Rozi»), of:oky:{k}:{id} (confirmed),
of:bk:{k}:{id} (back to the manager keyboard), of:ch:{k}:{id} (changes / recalc, asks the
comment), of:no:{k}:{id} (declined, asks the reason), of:q (cancel a typed answer)."""

from __future__ import annotations

from bot.common.kb import b, ik, url_button

OPEN_PANEL = "🌐 Saytda ochish"
DUE_BTN = "🕒 Muddatni o'zgartirish"

ANSWER_BTNS = {
    "d": ("✅ Tasdiqladi", "✏️ O'zgartirish kerak", "❌ Rad etdi"),
    "p": ("✅ Rozi", "🔁 Qayta hisoblash", "❌ Narxi qoniqtirmadi"),
}


def work_kb(k: str, oid: int, url: str = ""):
    """Assignee card: deadline + site. NO «Tayyor» (pressed on the site only)."""
    return ik([[b(DUE_BTN, f"of:dm:{k}:{oid}")], [url_button(OPEN_PANEL, url)] if url else []])


def due_kb(k: str, oid: int, url: str = ""):
    return ik(
        [
            [
                b("1 kunga", f"of:dp:1d:{k}:{oid}"),
                b("2 kunga", f"of:dp:2d:{k}:{oid}"),
                b("3 kunga", f"of:dp:3d:{k}:{oid}"),
            ],
            [b("🕒 Vaqtni yozaman", f"of:dc:{k}:{oid}")],
            [b("↩️ Orqaga", f"of:bw:{k}:{oid}")],
            [url_button(OPEN_PANEL, url)] if url else [],
        ]
    )


def present_kb(k: str, oid: int, url: str = ""):
    ok, ch, no = ANSWER_BTNS[k]
    return ik(
        [
            [b(ok, f"of:ok:{k}:{oid}")],
            [b(ch, f"of:ch:{k}:{oid}")],
            [b(no, f"of:no:{k}:{oid}")],
            [url_button(OPEN_PANEL, url)] if url else [],
        ]
    )


def confirm_kb(k: str, oid: int, url: str = ""):
    return ik(
        [
            [b("✅ Ha, mijoz " + ("tasdiqladi" if k == "d" else "rozi"), f"of:oky:{k}:{oid}")],
            [b("↩️ Orqaga", f"of:bk:{k}:{oid}")],
            [url_button(OPEN_PANEL, url)] if url else [],
        ]
    )


def cancel_kb():
    return ik([[b("❌ Bekor qilish", "of:q")]])


def site_kb(url: str):
    return ik([[url_button(OPEN_PANEL, url)]]) if url else None
