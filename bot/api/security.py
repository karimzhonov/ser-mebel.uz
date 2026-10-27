"""FastAPI dependency: verify the backend's HMAC signature (docs/BOT_CONTRACT.md)."""

from fastapi import HTTPException, Request

from bot.backend.signing import HEADER_ACTOR, HEADER_NONCE, HEADER_SIG, HEADER_TS, verify


async def verify_signature(request: Request) -> bytes:
    """Returns the raw body. 403 on a bad/stale signature."""
    body = await request.body()
    path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    ok = verify(
        request.headers.get(HEADER_SIG, ""),
        request.headers.get(HEADER_TS),
        request.method,
        path,
        request.headers.get(HEADER_ACTOR, ""),
        body,
        nonce=request.headers.get(HEADER_NONCE, ""),
    )
    if not ok:
        raise HTTPException(403, "bad signature")
    return body
