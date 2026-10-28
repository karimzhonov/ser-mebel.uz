"""Finance test kit: members, a site order and the bot-channel fixtures (api/tests/botkit.py:
bot_client signs requests like the bot service, bot_events collects the events the backend
queues for the bot)."""

import pytest

from api.tests.botkit import (  # noqa: F401
    bot_client,
    bot_events,
    contract,
    fake_replay_cache,
    members,
    site_order,
)
from api.tests.conftest import api, make_staff  # noqa: F401 - reuse the API client fixtures


@pytest.fixture(autouse=True)
def _finance_config(settings, db):
    from constance import config

    settings.TELEGRAM_BOT_TOKEN = "123456:TEST-BOT-TOKEN"
    config.FIN_USD_RATE = 12000.0
    config.FIN_CHANNEL_ID = ""
