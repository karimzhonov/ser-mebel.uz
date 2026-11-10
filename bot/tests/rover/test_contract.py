"""Fixtures from docs/bot_contract render (skipped until the backend wrote them)."""

import pytest

import bot.rover  # noqa: F401
from bot.notify.registry import dispatch

from .conftest import fake_bot, fixture


@pytest.mark.parametrize("event", ["check", "checked"])
async def test_event_fixtures_render(event):
    fx = fixture(f"event.rover.{event}")
    if fx is None:
        pytest.skip("fixture not written yet")
    env = (
        fx
        if "event" in fx
        else {"id": "00000000-0000-0000-0000-000000009800", "event": f"rover.{event}", "data": fx}
    )
    await dispatch(env, fake_bot())


def test_dto_and_confirm_response_fixtures_have_card_fields():
    from bot.rover import texts as T

    dto = fixture("dto.rover_task.1")
    resp = fixture("misc.rover_confirm_response")
    if dto is None and resp is None:
        pytest.skip("fixtures not written yet")
    for t in (dto, (resp or {}).get("rover")):
        if t:
            assert "Buyurtma" in T.card(t)
