import hmac
import json
import logging
from urllib.parse import unquote

from aiogram.exceptions import TelegramAPIError
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from api.schemas import MessageSchema, NotifyEnvelope
from api.security import verify_signature
from bot import bot, send_message
from bot.common.rds import get_redis
from bot.notify.registry import BadEventData, UnknownEvent, dispatch
from bot.webhook import feed_update, webhook_secret

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhook")
async def webhook(request: Request) -> None:
    got = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not hmac.compare_digest(got.encode(), webhook_secret().encode()):
        raise HTTPException(403, "bad secret token")
    update = await request.json()
    await feed_update(update)


@router.post("/user/{chat_id}/message")
async def message(chat_id: str, body: bytes = Depends(verify_signature)):
    try:
        data = MessageSchema(**json.loads(body))
    except (ValueError, TypeError) as e:
        raise HTTPException(400, f"bad body: {e}")
    try:
        return await send_message(chat_id=chat_id, **data.model_dump())
    except ConnectionError as e:
        raise HTTPException(400, {"status": "error", "message": str(e)})


@router.post("/notify")
async def notify(body: bytes = Depends(verify_signature)):
    try:
        env = NotifyEnvelope(**json.loads(body))
    except (ValueError, TypeError) as e:
        raise HTTPException(400, f"bad envelope: {e}")
    r = get_redis()
    key = f"dedup:evt:{env.id}"
    if not await r.set(key, 1, nx=True, ex=86400):
        return {"ok": True, "duplicate": True}
    try:
        delivered = await dispatch(env.model_dump(), bot)
    except (UnknownEvent, BadEventData) as e:
        await r.delete(key)
        raise HTTPException(400, str(e))
    except Exception:
        await r.delete(key)  # let the backend's retry run again
        logger.exception("notify %s failed", env.event)
        raise
    return {"ok": True, "delivered": delivered}


@router.get("/files/{file_id:path}")
async def files(file_id: str, _: bytes = Depends(verify_signature)):
    file_id = unquote(file_id)
    try:
        f = await bot.get_file(file_id)
        buf = await bot.download_file(f.file_path) if f.file_path else None
    except TelegramAPIError:
        raise HTTPException(404, "file not found")
    if buf is None:
        raise HTTPException(404, "file not found")
    path = (f.file_path or "").lower()
    ctype = (
        "image/jpeg"
        if path.endswith((".jpg", ".jpeg"))
        else "image/png" if path.endswith(".png") else "application/octet-stream"
    )
    return Response(content=buf.read(), media_type=ctype)
