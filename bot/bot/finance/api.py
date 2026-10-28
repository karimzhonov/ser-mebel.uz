"""Small backend lookups used all over the finance handlers (with a 60 s Redis cache for
the things that rarely change: config, categories, workers, cars)."""

from __future__ import annotations

import json
import logging
from decimal import Decimal, InvalidOperation

from bot.backend.client import NotFound
from bot.common.rds import get_redis

logger = logging.getLogger(__name__)

CACHE_TTL = 60


def D(v) -> Decimal:
    try:
        return Decimal(str(v if v is not None else 0))
    except InvalidOperation:
        return Decimal(0)


async def _cached(key: str, loader, ttl: int = CACHE_TTL):
    r = get_redis()
    try:
        raw = await r.get(f"cache:fin:{key}")
        if raw:
            return json.loads(raw)
    except Exception:  # noqa: BLE001 - the cache is optional
        logger.warning("cache read failed for %s", key)
    value = await loader()
    try:
        await r.set(f"cache:fin:{key}", json.dumps(value), ex=ttl)
    except Exception:  # noqa: BLE001
        logger.warning("cache write failed for %s", key)
    return value


async def drop_cache(*keys: str) -> None:
    try:
        await get_redis().delete(*[f"cache:fin:{k}" for k in keys])
    except Exception:  # noqa: BLE001
        pass


async def config(ctx) -> dict:
    return await _cached("config", lambda: ctx.get("finance/config/"))


async def usd_rate(ctx) -> Decimal:
    return D((await config(ctx)).get("usd_rate"))


async def categories(ctx, kind: str | None = None) -> list[dict]:
    return await _cached(f"cats:{kind or ''}", lambda: ctx.get("finance/categories/", kind=kind))


async def category(ctx, code) -> dict | None:
    if not code:
        return None
    for c in await categories(ctx):
        if c["code"] == code:
            return c
    return None


async def workers(ctx) -> list[dict]:
    return await _cached("workers", lambda: ctx.get("finance/workers/"))


async def cars(ctx) -> list[dict]:
    return await _cached("cars", lambda: ctx.get("finance/cars/"))


async def order_info(ctx, ref) -> dict | None:
    """OrderCard (stats included) or None when there is no such order."""
    if not ref:
        return None
    try:
        return await ctx.get(f"finance/orders/{ref}/")
    except NotFound:
        return None


async def order_label(ctx, ref) -> dict | None:
    """Just {ref, client} (cached 5 min) - for cards that only name the order."""
    if not ref:
        return None

    async def load():
        info = await order_info(ctx, ref)
        return {"ref": info["ref"], "client": info["client"]} if info else {}

    got = await _cached(f"order:{ref}", load, ttl=300)
    return got or None


async def balance(ctx, tg) -> Decimal:
    return D((await ctx.get(f"finance/members/{tg}/balance/")).get("balance"))


async def member(ctx, tg) -> dict | None:
    try:
        return await ctx.get(f"finance/members/{tg}/")
    except NotFound:
        return None


async def resolve_op_extras(ctx, op: dict) -> dict:
    """What `op_card` needs besides the operation: the order's client and worker info."""
    order = await order_label(ctx, op.get("order_ref")) if op.get("order_ref") else None
    wl = await workers(ctx) if op.get("worker") else []
    return {"order": order, "workers": wl}
