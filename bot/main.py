from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routes import router
from bot.backend.client import backend
from bot.utils import register_webhook


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await backend.close()


app = FastAPI(lifespan=lifespan)
app.include_router(router)
register_webhook(app)
