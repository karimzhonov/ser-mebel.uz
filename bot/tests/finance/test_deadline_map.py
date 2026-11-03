"""finance.deadline: the map link is the backend's Yandex map_url, never Google."""

import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import bot.finance  # noqa: F401  (registers the finance.* renderers)
from bot.notify.registry import dispatch

from .conftest import fx


def fake_bot():
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=900))
    return bot


async def _render(order_extra, key="3", drop=()):
    env = copy.deepcopy(fx("event.finance.deadline"))
    env["data"]["key"] = key
    for k in drop:
        env["data"]["order"].pop(k, None)
    env["data"]["order"].update(order_extra)
    bot = fake_bot()
    await dispatch(env, bot)
    return bot.send_message.call_args_list[0].args[1]


async def test_map_url_is_used_when_present(be):
    url = "https://yandex.uz/maps/?ll=69.279737,41.311081&pt=69.279737,41.311081&z=17&l=map"
    text = await _render({"lat": "41.311081", "lon": "69.279737", "map_url": url})
    assert 'href="https://yandex.uz/maps/?ll=69.279737,41.311081' in text
    assert "Yandex xaritada ochish" in text
    assert "google" not in text


async def test_falls_back_to_yandex_text_search(be):
    text = await _render({"lat": None, "lon": None, "map_url": None})
    assert 'href="https://yandex.uz/maps/?text=Chilonzor%205%2C%20Toshkent"' in text
    assert "google" not in text


async def test_old_payload_without_map_fields_still_renders(be):
    text = await _render({}, drop=("lat", "lon", "map_url"))
    assert "https://yandex.uz/maps/?text=" in text and "google" not in text


async def test_other_key_has_no_map(be):
    text = await _render({"map_url": "https://yandex.uz/maps/?x=1"}, key="1")
    assert "yandex" not in text


async def test_unmodified_contract_fixture_renders_its_map_url():
    fixture = fx("event.finance.deadline")["data"]["order"]
    assert fixture["map_url"]
    text = await _render({})
    assert "Yandex xaritada ochish" in text and "google" not in text
    assert fixture["map_url"].replace("&", "&amp;") in text
