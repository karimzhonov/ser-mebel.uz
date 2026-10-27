"""Minimal synchronous Telegram Bot API client for the finance bot.

Uses settings.TELEGRAM_BOT_TOKEN — the same BOT_TOKEN the bot/ service runs with
(the old Apps Script token is not used anywhere). Errors never raise into business
code: a failed send is logged and returns {"ok": False}, like tg_() in code.txt.
"""

from __future__ import annotations

import json
import logging
import threading
import time

import requests
from django.conf import settings

from ..text import clip

log = logging.getLogger("finance.telegram")

_local = threading.local()


def _token() -> str:
    return settings.TELEGRAM_BOT_TOKEN or ""


def _url(method: str) -> str:
    return f"https://api.telegram.org/bot{_token()}/{method}"


class Tracker:
    """Collects ids of messages sent into the current chat during one update, so
    «❌ Bekor qilish» can delete the whole flow (route_/_trk in code.txt)."""

    def __init__(self, chat_id):
        self.chat = str(chat_id)
        self.ids: list[int] = []


def set_tracker(tracker: Tracker | None):
    _local.tracker = tracker


def get_tracker() -> Tracker | None:
    return getattr(_local, "tracker", None)


def _track(result):
    tr = get_tracker()
    if tr and isinstance(result, dict) and result.get("message_id"):
        chat = result.get("chat") or {}
        if str(chat.get("id")) == tr.chat:
            tr.ids.append(result["message_id"])


def _scrub(text: str) -> str:
    tok = _token()
    return text.replace(tok, "***") if tok else text


def call(
    method: str, payload: dict | None = None, files: dict | None = None, timeout: int = 15
) -> dict:
    if not _token():
        log.warning("TELEGRAM_BOT_TOKEN is not set; %s skipped", method)
        return {"ok": False, "description": "no token"}
    last = None
    for attempt in range(2):  # short: the bot user is waiting
        try:
            if files:
                data = {
                    k: (
                        json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
                    )
                    for k, v in (payload or {}).items()
                    if v is not None
                }
                r = requests.post(_url(method), data=data, files=files, timeout=timeout)
            else:
                r = requests.post(_url(method), json=payload or {}, timeout=timeout)
            try:
                j = r.json()
            except ValueError:
                j = {"ok": False, "description": f"HTTP {r.status_code}"}
            if not j.get("ok"):
                if r.status_code == 429 and attempt < 1:
                    time.sleep(min(int((j.get("parameters") or {}).get("retry_after", 1)), 5))
                    continue
                log.warning("%s failed: %s", method, _scrub(str(j)[:300]))
            else:
                _track(j.get("result"))
            return j
        except requests.RequestException as e:
            last = e
            time.sleep(1 + attempt)
    log.warning("%s network error: %s", method, _scrub(str(last)))
    return {"ok": False, "description": "network error"}


def send(chat_id, text: str, kb: dict | None = None) -> dict:
    payload = {
        "chat_id": chat_id,
        "text": clip(text, 4096),
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if kb:
        payload["reply_markup"] = kb
    return call("sendMessage", payload)


def edit(chat_id, message_id, text: str, kb: dict | None = None) -> dict:
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": clip(text, 4096),
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if kb:
        payload["reply_markup"] = kb
    return call("editMessageText", payload)


def clear_kb(chat_id, message_id, kb: dict | None = None) -> dict:
    payload = {"chat_id": chat_id, "message_id": message_id}
    if kb:
        payload["reply_markup"] = kb
    return call("editMessageReplyMarkup", payload)


def delete(chat_id, message_id) -> dict:
    return call("deleteMessage", {"chat_id": chat_id, "message_id": message_id})


def answer_callback(cq_id: str, text: str = "") -> dict:
    return call("answerCallbackQuery", {"callback_query_id": cq_id, "text": text})


def send_photo(chat_id, photo, caption: str = "", kb: dict | None = None) -> dict:
    """photo: Telegram file_id (str) or PNG bytes."""
    payload = {"chat_id": chat_id, "caption": clip(caption, 1024), "parse_mode": "HTML"}
    if kb:
        payload["reply_markup"] = kb
    if isinstance(photo, (bytes, bytearray)):
        return call(
            "sendPhoto",
            payload,
            files={"photo": ("image.png", bytes(photo), "image/png")},
            timeout=60,
        )
    payload["photo"] = photo
    return call("sendPhoto", payload)


def edit_photo(chat_id, message_id, png: bytes, caption: str, kb: dict | None = None) -> dict:
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "media": {
            "type": "photo",
            "media": "attach://p",
            "caption": clip(caption, 1024),
            "parse_mode": "HTML",
        },
    }
    if kb:
        payload["reply_markup"] = kb
    return call(
        "editMessageMedia", payload, files={"p": ("image.png", png, "image/png")}, timeout=60
    )


def send_document(chat_id, content: bytes, filename: str, caption: str = "") -> dict:
    return call(
        "sendDocument",
        {"chat_id": chat_id, "caption": clip(caption, 1024)},
        files={"document": (filename, content, "application/octet-stream")},
        timeout=120,
    )


def download_file(file_id: str) -> tuple[bytes, str] | None:
    """Bytes of a Telegram file (receipt, feedback screenshot) for the site."""
    j = call("getFile", {"file_id": file_id})
    if not j.get("ok"):
        return None
    path = j["result"].get("file_path", "")
    try:
        r = requests.get(f"https://api.telegram.org/file/bot{_token()}/{path}", timeout=60)
        r.raise_for_status()
    except requests.RequestException as e:
        log.warning("file download failed: %s", _scrub(str(e)))
        return None
    ctype = (
        "image/jpeg"
        if path.lower().endswith((".jpg", ".jpeg"))
        else ("image/png" if path.lower().endswith(".png") else "application/octet-stream")
    )
    return r.content, ctype


# ---------------------------------------------------------------- keyboards
def ik(rows) -> dict:
    return {"inline_keyboard": [r for r in rows if r]}


def b(text: str, data: str) -> dict:
    return {"text": text, "callback_data": str(data)[:64]}


def url_button(text: str, url: str) -> dict:
    return {"text": text, "url": url}


def grid(buttons, n: int):
    return [buttons[i : i + n] for i in range(0, len(buttons), n)]


def reply_kb(rows) -> dict:
    return {"keyboard": [[{"text": t} for t in r] for r in rows], "resize_keyboard": True}


CANCEL = b("❌ Bekor qilish", "cancel")
