"""Inline keyboard of the detailing card: URL buttons only (no callbacks) — «✅ Bajardim»
opens the job on the site, where the detailer enters the squares and the services."""

from __future__ import annotations

from bot.common.kb import ik, url_button


def task_kb(url: str = "", folder_url: str | None = None, done: bool = False):
    rows = []
    if url:
        rows.append([url_button("🌐 Saytda ochish" if done else "✅ Bajardim", url)])
    if folder_url:
        rows.append([url_button("📁 Buyurtma fayllari", folder_url)])
    return ik(rows) or None
