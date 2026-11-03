"""The docs/bot_contract location fixtures driven through the bot's real handlers/keyboards."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import bot.crm  # noqa: F401  (registers crm.task_due)
from bot.notify.registry import dispatch

from .conftest import buttons, cbs
from .test_location import LAT, LON, allow, send_loc

CONTRACT = Path(__file__).resolve().parents[3] / "docs" / "bot_contract"


def fx(name):
    return json.loads((CONTRACT / f"{name}.json").read_text(encoding="utf-8"))


def fake_bot():
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=900))
    return bot


async def test_candidates_fixture_renders_a_target_keyboard(env):
    allow(env)
    cands = fx("misc.crm_location_candidates_response")
    env.backend.routes[("GET", "crm/locations/candidates/")] = cands
    await send_loc(env)
    last = env.session.last()
    assert cbs(last.reply_markup) == ["crm:loc:i:128", "crm:loc:m:57", "crm:loc:new", "crm:loc:x"]
    texts = [t for t, *_ in buttons(last.reply_markup)]
    assert texts[0] == "📋 #128 Ali Valiyev"  # no point yet -> no check mark
    assert texts[1].startswith("📐 05.11 10:00 Nazira") and texts[1].endswith("✅")


async def test_candidates_fixture_without_new_lead_hides_the_button(env):
    allow(env)
    cands = {**fx("misc.crm_location_candidates_response"), "can_new_lead": False}
    env.backend.routes[("GET", "crm/locations/candidates/")] = cands
    await send_loc(env)
    assert "crm:loc:new" not in cbs(env.session.last().reply_markup)


async def test_single_dto_fixture_works_as_a_candidate(env):
    allow(env)
    dto = fx("dto.location_target.1")
    env.backend.routes[("GET", "crm/locations/candidates/")] = {
        "items": [dto],
        "can_new_lead": False,
    }
    await send_loc(env)
    assert cbs(env.session.last().reply_markup)[0] == f"crm:loc:i:{dto['id']}"


async def test_post_body_has_the_shape_of_the_request_fixture(env):
    allow(env)
    req = fx("misc.crm_location_request")
    env.backend.routes[("GET", "crm/locations/candidates/")] = fx(
        "misc.crm_location_candidates_response"
    )
    env.backend.routes[("POST", "crm/locations/")] = fx("misc.crm_location_response")
    await send_loc(env, venue=req["address"])
    await env.cb(f"crm:loc:i:{req['target']['id']}")
    body = env.backend.to("crm/locations/")[0][2]
    assert body["target"] == req["target"]
    assert float(req["lat"]) == LAT and float(req["lon"]) == LON  # same point as the fixture
    assert float(body["lat"]) == float(req["lat"]) and float(body["lon"]) == float(req["lon"])
    assert body["address"] == req["address"]
    # only keys the contract knows (live is optional and only sent when true)
    assert set(body) <= set(req)


async def test_response_fixture_renders_confirmation_and_map_buttons(env):
    allow(env)
    res = fx("misc.crm_location_response")
    env.backend.routes[("GET", "crm/locations/candidates/")] = fx(
        "misc.crm_location_candidates_response"
    )
    env.backend.routes[("POST", "crm/locations/")] = res
    await send_loc(env)
    await env.cb("crm:loc:i:128")
    last = env.session.last()
    assert "Lokatsiya saqlandi" in last.text and "#128" in last.text
    assert "Ali Valiyev" in last.text and "+998901112244" in last.text
    assert "o'lchovga" in last.text  # filled: one metering
    assert "buyurtmaga" not in last.text
    assert buttons(last.reply_markup) == [
        ("🗺 Yandex xaritada", None, res["map_url"]),
        ("💻 Panelda ochish", None, res["url"]),
    ]
    assert await env.state() is None


async def test_response_fixture_without_filled_has_no_extra_note(env):
    allow(env)
    res = {**fx("misc.crm_location_response"), "filled": []}
    env.backend.routes[("GET", "crm/locations/candidates/")] = fx(
        "misc.crm_location_candidates_response"
    )
    env.backend.routes[("POST", "crm/locations/")] = res
    await send_loc(env)
    await env.cb("crm:loc:i:128")
    assert "ham qo'shildi" not in env.session.last().text


async def test_task_due_fixture_renders_without_a_map_button():
    bot = fake_bot()
    env = fx("event.crm.task_due")
    await dispatch(env, bot)
    call = bot.send_message.call_args_list[0]
    btns = buttons(call.kwargs["reply_markup"])
    assert not any("Yandex" in t for t, *_ in btns)
    assert call.args[0] == env["data"]["to"][0]


async def test_task_due_fixture_without_a_point_has_no_map_button():
    bot = fake_bot()
    env = copy.deepcopy(fx("event.crm.task_due"))
    env["data"]["invoice"].update(has_point=False, map_url=None)
    await dispatch(env, bot)
    btns = buttons(bot.send_message.call_args_list[0].kwargs["reply_markup"])
    assert not any("Yandex" in t for t, *_ in btns)
