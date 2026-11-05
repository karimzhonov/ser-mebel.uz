"""Router order and the backend contract fixtures (skipped until the backend side wrote them)."""

import pytest

from bot.notify.registry import dispatch

from .conftest import fake_bot, fixture


def test_router_order_metering_between_start_and_crm(env):
    names = [r.name for r in env.dp.sub_routers]
    assert names.index("start") < names.index("metering") < names.index("crm")


@pytest.mark.parametrize("event", ["assigned", "reminder", "digest", "changed"])
async def test_event_fixtures_render(event):
    fx = fixture(f"event.metering.{event}")
    if fx is None:
        pytest.skip("fixture not written yet")
    env = (
        fx
        if "event" in fx
        else {
            "id": "00000000-0000-0000-0000-000000009600",
            "event": f"metering.{event}",
            "data": fx,
        }
    )
    await dispatch(env, fake_bot())
