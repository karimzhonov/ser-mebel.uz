import os

from dotenv import load_dotenv

load_dotenv()

DEBUG = os.getenv('DEBUG', 'true') == 'true'
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
BASE_SITE = os.getenv('BASE_SITE')

# Backend inside the compose network; the finance bot forwards updates there.
BACKEND_URL = os.getenv("BACKEND_URL", "http://back:8000")
