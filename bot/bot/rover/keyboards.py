"""Inline keyboards of the rover card. callback_data (stable):
rv:ok:{id} («✅ Bajarildi», asks to confirm), rv:oky:{id} (confirmed),
rv:bk:{id} (back to the card keyboard)."""

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
