"""Keyboard helpers (aiogram types). `b()` clips callback_data to Telegram's 64 bytes."""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


def b(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=str(data)[:64])


def url_button(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=url)


def ik(rows) -> InlineKeyboardMarkup:
    """Inline keyboard from rows of buttons; empty rows are dropped."""
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows if r])


def grid(buttons: list, n: int) -> list[list]:
    return [buttons[i : i + n] for i in range(0, len(buttons), n)]


def reply_kb(rows) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t) for t in r] for r in rows], resize_keyboard=True
    )


CANCEL = b("❌ Bekor qilish", "cancel")
