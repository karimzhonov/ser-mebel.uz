"""Fixtures from docs/bot_contract render (skipped until the backend wrote them)."""

import pytest

import bot.painter  # noqa: F401
from bot.notify.registry import dispatch

from .conftest import fake_bot, fixture

EVENTS = ["task", "unassigned", "ready", "due_ask", "due_set", "remind", "done"]


@pytest.mark.parametrize("event", EVENTS)
async def test_event_fixtures_render(event):
    fx = fixture(f"event.painter.{event}")
    if fx is None:
        pytest.skip("fixture not written yet")
    env = (
        fx
        if "event" in fx
        else {"id": "00000000-0000-0000-0000-000000009800", "event": f"painter.{event}", "data": fx}
    )
    await dispatch(env, fake_bot())


def test_dto_and_done_response_fixtures_render():
    from bot.painter import texts as T

    dto = fixture("dto.painter_task.1")
    resp = fixture("misc.painter_done_response")
    if dto is None and resp is None:
        pytest.skip("fixtures not written yet")
    for t in (dto, (resp or {}).get("painter")):
        if t:
            assert "Buyurtma" in T.task_card(t) and "Buyurtma" in T.head_card(t)
