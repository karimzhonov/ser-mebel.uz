from django.conf import settings


def bot_link(start: str | int = "") -> str:
    """t.me deep link to the site bot (settings.TELEGRAM_BOT_USERNAME)."""
    url = f"https://t.me/{settings.TELEGRAM_BOT_USERNAME}"
    return f"{url}?start={start}" if start != "" else url
