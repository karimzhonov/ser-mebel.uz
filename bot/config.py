import os

from dotenv import load_dotenv

load_dotenv()

DEBUG = os.getenv("DEBUG", "true") == "true"
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
BASE_SITE = os.getenv("BASE_SITE") or ""

# Backend inside the compose network; every business call goes to {BACKEND_URL}/api/v1/bot/.
BACKEND_URL = os.getenv("BACKEND_URL", "http://back:8000")

# FSM storage, dedup keys and per-user locks. Db 1: Celery (the backend) uses db 0.
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/1")

# Username of this bot without "@" (used in links shown to users).
TELEGRAM_BOT_USERNAME = (os.getenv("TELEGRAM_BOT_USERNAME") or "").lstrip("@")
