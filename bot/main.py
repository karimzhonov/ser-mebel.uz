from fastapi import FastAPI

from db.utils import register_tortoise
from api.routes import router
from bot.utils import register_webhook

app = FastAPI()
register_tortoise(app)
app.include_router(router)
register_webhook(app)