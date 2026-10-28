"""HR (davomat) tests: the HR kit plus the bot-channel fixtures."""

from accounting.tests.conftest import api, make_staff  # noqa: F401
from api.tests.botkit import (  # noqa: F401
    bot_client,
    bot_events,
    contract,
    fake_replay_cache,
    site_order,
)
from hr.tests.hrkit import (  # noqa: F401
    GROUP,
    Clock,
    _fresh_settings_cache,
    boss,
    clock,
    group,
    ts,
)
