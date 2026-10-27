"""Celery tasks shared by all apps."""

import logging

from celery import shared_task

from .bot_notify import BotUnavailable, post_envelope

log = logging.getLogger("core.tasks")


@shared_task(
    bind=True,
    autoretry_for=(BotUnavailable,),
    max_retries=8,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=False,
)
def notify_bot(self, envelope: dict):
    """Deliver one event envelope to the bot (`POST /notify`). Connection errors and 5xx
    are retried with backoff and the SAME envelope id (the bot dedups on it); a 4xx is
    logged and dropped. After an `hr.*` event the delivery results update Employee.can_dm."""
    answer = post_envelope(envelope)
    if str(envelope.get("event", "")).startswith("hr."):
        from hr.services import record_dm_results

        record_dm_results(answer.get("delivered") or [])
    return bool(answer.get("ok"))
