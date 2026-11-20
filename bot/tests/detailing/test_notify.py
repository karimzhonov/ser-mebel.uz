"""detailing.task renders the detailer's card: deadline, client, «✅ Bajardim» site link."""

import copy

import bot.detailing  # noqa: F401
from bot.detailing import keyboards as K
from bot.detailing import texts as T
from bot.notify.registry import dispatch

from ..rover.conftest import fake_bot, fixture

URL = "https://ser-mebel.uz/production/detailing?open=31"
TASK = {
    "id": 31,
    "order": {"id": 88, "number": 1042},
    "client": {"fio": "Ali <Valiyev>", "phone": "+998901112244"},
    "address": "Chilonzor 7 & 12",
    "map_url": "https://yandex.com/maps/?pt=69.24,41.29",
    "end_date": "2026-12-05",
    "due_at": "2026-11-21T18:00:00",
    "done": False,
    "url": URL,
    "folder_url": "https://ser-mebel.uz/files/120",
}


def _env(data, eid="00000000-0000-0000-0000-000000009901"):
    return {"id": eid, "event": "detailing.task", "data": data}


async def test_card_sent_to_every_detailer_with_site_button():
    bot = fake_bot()
    await dispatch(_env({"detailing": TASK, "how": "new", "to": [11, 12]}), bot)
    assert bot.send_message.await_count == 2
    call = bot.send_message.await_args
    kw, text = call.kwargs, call.args[1]
    assert "Yangi detalirovka" in text and "№1042" in text
    assert "Ali &lt;Valiyev&gt;" in text and "+998901112244" in text
    assert "Chilonzor 7 &amp; 12" in text
    assert "21.11.2026 18:00" in text and "05.12.2026" in text
    rows = kw["reply_markup"].inline_keyboard
    assert rows[0][0].text == "✅ Bajardim" and rows[0][0].url == URL
    assert rows[1][0].url == TASK["folder_url"]


def test_moved_header_and_done_card():
    assert "muddati o'zgardi" in T.task_card(TASK, "moved")
    done = copy.deepcopy(TASK) | {"done": True}
    assert "✅ Bajarilgan" in T.task_card(done)
    assert K.task_kb(URL, None, done=True).inline_keyboard[0][0].text == "🌐 Saytda ochish"


def test_no_due_no_address():
    t = copy.deepcopy(TASK) | {"due_at": None, "address": "", "map_url": None}
    text = T.task_card(t)
    assert "belgilanmagan" in text and "📍" not in text


async def test_contract_fixture_renders():
    fx = fixture("event.detailing.task")
    assert fx is not None
    bot = fake_bot()
    await dispatch(fx, bot)
    assert bot.send_message.await_count == len(fx["data"]["to"])
