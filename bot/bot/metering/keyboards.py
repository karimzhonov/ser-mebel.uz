"""Inline keyboards of the zamer cards. callback_data (stable):
mt:ms:{id} (asks «O'lchov oldim»), mt:msy:{id} (confirmed), mt:rs:{id} (reschedule menu),
mt:rp:{1h|tm|2d}:{id} (preset), mt:rc:{id} (typed time), mt:cn:{id} (asks the reason),
mt:bk:{id} (back to the card keyboard), mt:q (cancel a typed answer)."""

from __future__ import annotations

from bot.common.kb import b, ik, url_button

OPEN_PANEL = "🌐 Saytda ochish"
MAP_BTN = "📍 Xarita"
UPLOAD_BTN = "📤 Saytda yuklash"
MEASURED_BTN = "✅ O'lchov oldim"
RESCHEDULE_BTN = "🕒 Vaqtni o'zgartirish"
CANCEL_BTN = "❌ Bekor bo'ldi"
OPEN_STATUSES = ("created", "other_day")


def _links(url: str, map_url: str, open_text: str = OPEN_PANEL) -> list:
    row = []
    if map_url:
        row.append(url_button(MAP_BTN, map_url))
    if url:
        row.append(url_button(open_text, url))
    return row


def card_kb(mid: int, status: str, url: str = "", map_url: str = ""):
    """Keyboard by status; None when the card is final."""
    if status in OPEN_STATUSES:
        return ik(
            [
                [b(MEASURED_BTN, f"mt:ms:{mid}")],
                [b(RESCHEDULE_BTN, f"mt:rs:{mid}")],
                [b(CANCEL_BTN, f"mt:cn:{mid}")],
                _links(url, map_url),
            ]
        )
    if status == "metering_done" and url:
        return ik([[url_button(UPLOAD_BTN, url)]])
    return None


def confirm_kb(mid: int, url: str = "", map_url: str = ""):
    return ik(
        [
            [b("✅ Ha, o'lchov oldim", f"mt:msy:{mid}")],
            [b("↩️ Orqaga", f"mt:bk:{mid}")],
            _links(url, map_url),
        ]
    )


def resched_kb(mid: int, url: str = "", map_url: str = ""):
    return ik(
        [
            [b("⏰ 1 soatdan keyin", f"mt:rp:1h:{mid}")],
            [b("🌅 Ertaga", f"mt:rp:tm:{mid}"), b("📅 2 kundan keyin", f"mt:rp:2d:{mid}")],
            [b("🕒 Vaqtni yozaman", f"mt:rc:{mid}")],
            [b("↩️ Orqaga", f"mt:bk:{mid}")],
            _links(url, map_url),
        ]
    )


def cancel_kb():
    return ik([[b("❌ Bekor qilish", "mt:q")]])


def agenda_kb(url: str):
    return ik([[url_button("🗓 Zamerlar ro'yxati", url)]]) if url else None


def site_kb(url: str):
    return ik([[url_button(OPEN_PANEL, url)]]) if url else None
