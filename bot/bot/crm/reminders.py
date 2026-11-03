"""Remember the `crm.task_due` reminders the bot sent, so they can be edited when the task
is closed / moved elsewhere (panel, lead closing). Redis list `crm:msg:{task_id}` of JSON
`{chat_id, message_id, html}`, 14 days. Redis is shared by all uvicorn workers."""

from __future__ import annotations

import json
import logging

from bot.common.rds import get_redis

log = logging.getLogger("bot.crm.reminders")

TTL = 14 * 24 * 3600


def _key(task_id) -> str:
    return f"crm:msg:{int(task_id)}"


async def remember(task_id, chat_id, message_id, html: str) -> None:
    try:
        r = get_redis()
        key = _key(task_id)
        await r.rpush(
            key,
            json.dumps({"chat_id": chat_id, "message_id": message_id, "html": html}),
        )
        await r.expire(key, TTL)
    except Exception:  # noqa: BLE001 - losing the mapping only costs a stale keyboard
        log.warning("could not remember reminder of task %s", task_id, exc_info=True)


async def take(task_id) -> list[dict]:
    """Read and delete the stored reminders of the task."""
    try:
        r = get_redis()
        key = _key(task_id)
        # one MULTI/EXEC: a reminder stored in between is neither lost nor left unedited
        async with r.pipeline(transaction=True) as p:
            p.lrange(key, 0, -1)
            p.delete(key)
            raw, _ = await p.execute()
    except Exception:  # noqa: BLE001
        log.warning("could not load reminders of task %s", task_id, exc_info=True)
        return []
    out = []
    for item in raw or []:
        try:
            out.append(json.loads(item))
        except (TypeError, ValueError):
            continue
    return out


async def forget(task_id) -> None:
    """The bot itself finished / snoozed the task (its message is already edited)."""
    try:
        await get_redis().delete(_key(task_id))
    except Exception:  # noqa: BLE001
        log.warning("could not forget reminders of task %s", task_id, exc_info=True)
