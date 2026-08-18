import json
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def format_phone(phone) -> str | None:
    """PhoneNumber -> '998971234567' (no leading +), or None if unusable."""
    if not phone:
        return None
    try:
        return phone.as_e164.lstrip("+")
    except Exception:
        return None


def absolute_url(path: str) -> str:
    if not settings.ADMIN_BASE_URL:
        return str(path)
    return settings.ADMIN_BASE_URL.rstrip("/") + str(path)


def send_bulk_sms(messages: list[dict]) -> None:
    """messages: [{'phone': '998...', 'text': '...'}, ...]. Fire-and-forget, never raises."""
    if not messages or not settings.SMS_LOGIN:
        return
    for i in range(0, len(messages), 100):
        chunk = messages[i : i + 100]
        payload = {
            "login": settings.SMS_LOGIN,
            "password": settings.SMS_PASSWORD,
            "data": json.dumps(chunk, ensure_ascii=False),
        }
        if settings.SMS_NICKNAME:
            payload["nickname"] = settings.SMS_NICKNAME
        try:
            resp = requests.post(settings.SMS_GATEWAY_URL, data=payload, timeout=10)
        except requests.RequestException as e:
            logger.warning("SMS gateway request failed: %s", e)
            continue
        _log_gateway_errors(resp)


def _log_gateway_errors(resp) -> None:
    try:
        data = resp.json()
    except ValueError:
        logger.warning("SMS gateway returned non-JSON response: %s", resp.text[:200])
        return
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return
    for item in data:
        if not isinstance(item, dict) or not item.get("error"):
            continue
        msg = item.get("text") or item.get("error_text")
        logger.warning(
            "SMS gateway error %s: %s (recipient=%s)",
            item.get("error_no"),
            msg,
            item.get("recipient"),
        )
