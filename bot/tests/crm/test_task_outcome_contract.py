"""docs/bot_contract task-outcome fixtures driven through the bot's real handlers."""

import json
from pathlib import Path

from .conftest import buttons, cbs
from .test_task_outcome import kb_of, tap

CONTRACT = Path(__file__).resolve().parents[3] / "docs" / "bot_contract"


def fx(name):
    return json.loads((CONTRACT / name).read_text(encoding="utf-8"))


DETAIL = fx("misc.crm_task_detail_response.json")
REQ = fx("misc.crm_task_done_request.json")
RESP = fx("misc.crm_task_done_response.json")
TID = DETAIL["task"]["id"]  # 41

CODES = {
    "re_phone": "rp",
    "given_info": "gi",
    "given_location": "gl",
    "price_problem": "pp",
    "dont_need": "dn",
    "declined": "dc",
}


async def test_picker_built_from_detail_fixture(env):
    env.backend.routes[("GET", f"crm/tasks/{TID}/")] = DETAIL
    rows = {
        "inline_keyboard": [
            [{"text": "💻 Panelda ochish", "url": DETAIL["url"]}],
            [{"text": "🗺 Yandex xaritada", "url": DETAIL["invoice"]["map_url"]}],
            [{"text": "✅ Bajarildi", "callback_data": f"crm:done:{TID}"}],
        ]
    }
    await tap(env, f"crm:done:{TID}", markup=rows)
    expected = [f"crm:do:{CODES[o]}:{TID}" for o in DETAIL["outcomes"] if o in CODES]
    got = cbs(kb_of(env))
    assert got == expected + [f"crm:dx:{TID}"]
    # go_for_measured is offered as a URL button to the panel from the fixture
    assert [u for _, _, u in buttons(kb_of(env)) if u].count(DETAIL["url"]) == 2  # panel row + zamer button


async def test_post_body_equals_request_fixture(env):
    env.backend.routes[("POST", f"crm/tasks/{TID}/done/")] = RESP
    # the fixture's choice: re_phone + tomorrow (no note is sent from buttons)
    await tap(env, f"crm:dt:rp:tm:{TID}")
    body = env.backend.to(f"crm/tasks/{TID}/done/")[0][2]
    assert body == {k: v for k, v in REQ.items() if k != "note"}
    assert set(REQ) <= {"note", "outcome", "next_task"}


async def test_finish_text_rendered_from_response_fixture(env):
    env.backend.routes[("POST", f"crm/tasks/{TID}/done/")] = RESP
    await tap(env, f"crm:dt:rp:tm:{TID}")
    t = env.session.edits()[0].text
    assert t.startswith(
        f"✅ Bajarildi — {RESP['by_name']}\n➡️ {RESP['invoice']['solution_label']}\n"
        "⏰ Keyingi qo'ng'iroq: 04.11 10:00"
    )
    assert "🗂" not in t  # closed_tasks == 0
    assert "Vazifa vaqti keldi" in t
