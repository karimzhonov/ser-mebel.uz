"""Backend plumbing of the warehouse part: signed calls to `/api/v1/bot/warehouse/...` and
the error -> text mapping. Every rule (who is the keeper, limits, prices) lives in the
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

DOWN_TEXT = "⚠️ Server bilan aloqa yo'q. Birozdan keyin qayta urinib ko'ring."
ALREADY = "Allaqachon bajarilgan."
PERIODS = {"d": "today", "w": "week", "m": "month"}


async def call(method: str, path: str, *, actor, json=None, params=None):
    return await backend.request(method, path, actor=actor, json=json, params=params)


def err_text(e: BackendError) -> str:
    if isinstance(e, BackendDown):
        return DOWN_TEXT
    if isinstance(e, Conflict):
        return e.detail or ALREADY
    return f"❗ {e.detail}" if e.detail else "❗ Xatolik."


async def upload_photo(actor, pid, content: bytes, file_id: str | None = None):
    """Multipart upload of one picture; `file_id` (Telegram) is only a cache hint."""
    return await backend.request(
        "POST",
        f"warehouse/products/{pid}/photos/",
        actor=actor,
        json={"tg_file_id": file_id} if file_id else None,
        files={"file": ("photo.jpg", content, "image/jpeg")},
    )


async def photo_bytes(actor, photo_id) -> bytes:
    res = await backend.request("GET", f"warehouse/photos/{photo_id}/file/", actor=actor, raw=True)
    return res.content


async def cache_file_id(actor, photo_id, file_id: str) -> None:
    await call(
        "POST", f"warehouse/photos/{photo_id}/tg-file/", actor=actor, json={"file_id": file_id}
    )


async def order_candidates(actor, q: str = "") -> list[dict]:
    res = await call("GET", "warehouse/orders/", actor=actor, params={"q": q} if q else None)
    return (res or {}).get("items") or []


async def resolve_orders(actor, text: str) -> dict:
    """{"items": [WhOrderRef], "unknown": [str]} for typed IDs."""
    return await call("POST", "warehouse/orders/resolve/", actor=actor, json={"text": text})
