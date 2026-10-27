from contextlib import asynccontextmanager

from fastapi import FastAPI

from bot.webhook import delete_webhook, set_webhook
from config import DEBUG


def register_webhook(app: FastAPI):
    from fastapi.routing import _merge_lifespan_context

    @asynccontextmanager
    async def webhook_lifespan(app_instance: FastAPI):
        if not DEBUG:
            await set_webhook()
        yield
        if not DEBUG:
            await delete_webhook()

    original_lifespan = app.router.lifespan_context
    app.router.lifespan_context = _merge_lifespan_context(webhook_lifespan, original_lifespan)
