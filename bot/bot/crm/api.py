"""Backend plumbing of the CRM part: signed calls to `/api/v1/bot/crm/...` and the
error -> text mapping. All rules (who may add a lead, who may close a task) live in the
backend."""

from __future__ import annotations

from bot.backend.client import (  # noqa: F401  (re-exported for the handlers)
    BackendDown,
    BackendError,
    Conflict,
    Forbidden,
    NotFound,
    ServiceRefusal,
    backend,
)

from .texts import ALREADY_DONE

DOWN_TEXT = "⚠️ Server bilan aloqa yo'q. Birozdan keyin qayta urinib ko'ring."


async def call(method: str, path: str, *, actor, json=None, params=None):
    return await backend.request(method, path, actor=actor, json=json, params=params)


def err_text(e: BackendError) -> str:
    if isinstance(e, BackendDown):
        return DOWN_TEXT
    if isinstance(e, Conflict):
        return e.detail or ALREADY_DONE
    return f"❗ {e.detail}" if e.detail else "❗ Xatolik."
