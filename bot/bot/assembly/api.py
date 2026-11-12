"""Backend plumbing of the assembly part: signed calls to `/api/v1/bot/assemblies/...` and
the error -> text mapping. Who may finish / pick and the state rules live in the backend."""

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

DOWN_TEXT = "⚠️ Server bilan aloqa yo'q. Birozdan keyin qayta urinib ko'ring."
ALREADY = "Allaqachon bajarilgan"


async def call(method: str, path: str, *, actor, json=None, params=None):
    return await backend.request(method, path, actor=actor, json=json, params=params)


def err_text(e: BackendError) -> str:
    if isinstance(e, BackendDown):
        return DOWN_TEXT
    if isinstance(e, Conflict):
        return e.detail or ALREADY
    return f"❗ {e.detail}" if e.detail else "❗ Xatolik."
