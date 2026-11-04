"""Router order and the backend contract fixtures (skipped until the backend side wrote them)."""

import pytest

from bot.notify.registry import dispatch

from .conftest import fake_bot, fixture


def test_router_order_offer_between_metering_and_crm(env):
    names = [r.name for r in env.dp.sub_routers]
    assert names.index("metering") < names.index("offer") < names.index("crm")


def test_common_cardstore_keeps_metering_keys():
    from bot.common.cards import CardStore
    from bot.metering import messages

    assert messages._key(7) == "met:msg:7" and messages._ver(7) == "met:ver:7"
    assert CardStore("off")._key("d12") == "off:msg:d12"


@pytest.mark.parametrize("event", ["assigned", "reminder", "present", "changed", "order_ready"])
async def test_event_fixtures_render(event):
    import bot.offer  # noqa: F401

    fx = fixture(f"event.offer.{event}")
    if fx is None:
        pytest.skip("fixture not written yet")
    env = (
        fx
        if "event" in fx
        else {
            "id": "00000000-0000-0000-0000-000000009700",
            "event": f"offer.{event}",
            "data": fx,
        }
    )
    await dispatch(env, fake_bot())
