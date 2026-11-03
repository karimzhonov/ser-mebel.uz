"""«Yangi mijoz»: dispatcher order, entry filter, full FSM flows, save rules."""

import pytest

from bot.backend.client import ServiceRefusal

from .conftest import buttons, cbs

LEAD_RESPONSE = {
    "invoice": {
        "id": 41,
        "client": {"fio": "Karim Aliyev", "phone": "+998901234567"},
        "source": "telegram",
        "source_label": "Telegram",
        "solution": None,
        "solution_label": None,
        "assigned": {"id": 3, "name": "Aziz"},
        "last_note": "Salom",
    },
    "task": {
        "id": 8,
        "text": "Mijozga qo'ng'iroq qilish",
        "due_at": "2026-11-04T10:00:00",
        "is_done": False,
        "assigned": {"id": 3, "name": "Aziz"},
    },
    "client_existed": False,
    "url": "https://ser-mebel.uz/call-center?open=41",
}
NO_CLIENT = {"exists": False, "fio": None, "invoices_count": 0, "open_invoice": None}


def script(env, **over):
    r = env.backend.routes
    r[("GET", "crm/clients/")] = over.get("clients", NO_CLIENT)
    r[("POST", "crm/leads/")] = over.get("leads", LEAD_RESPONSE)
    r[("POST", "crm/due/parse/")] = over.get("parse", {"due_at": "2026-11-05T14:00:00"})


# ------------------------------------------------------------------ typed flow
async def test_full_typed_flow_with_custom_time(env):
    script(env)
    await env.text("🆕 Yangi mijoz")
    assert await env.state() == "Lead:name"
    await env.text("Karim")
    assert await env.state() == "Lead:phone"
    await env.text("+998 90 123 45 67")
    assert await env.state() == "Lead:source"
    assert env.backend.to("crm/clients/")[0][3] == {"phone": "+998 90 123 45 67"}
    kb = env.session.last().reply_markup
    assert [c for c in cbs(kb) if c.startswith("crm:src:")] == [
        f"crm:src:{k}"
        for k in ("telegram", "instagram", "phone", "showroom", "recommendation", "other")
    ]
    await env.cb("crm:src:instagram")
    assert await env.state() == "Lead:note"
    await env.text("Oshxona kerak")
    assert await env.state() == "Lead:remind"
    assert set(cbs(env.session.last().reply_markup)) >= {
        "crm:rem:today", "crm:rem:tomorrow", "crm:rem:custom", "crm:rem:none",
    }  # fmt: skip
    await env.cb("crm:rem:custom")
    assert await env.state() == "Lead:remind_custom"
    await env.text("05.11 14:00")
    assert env.backend.to("crm/due/parse/")[0][2] == {"text": "05.11 14:00"}
    assert await env.state() == "Lead:confirm"
    summary = env.session.last().text
    assert "Karim" in summary and "Instagram" in summary and "05.11 14:00" in summary
    await env.cb("crm:save")
    posts = env.backend.to("crm/leads/")
    assert len(posts) == 1
    assert posts[0][2] == {
        "name": "Karim",
        "phone": "+998 90 123 45 67",
        "source": "instagram",
        "note": "Oshxona kerak",
        "remind": {"at": "2026-11-05T14:00"},
    }
    assert await env.state() is None
    last = env.session.last()
    assert "Ariza #41 yaratildi" in last.text
    assert ("💻 Panelda ochish", None, "https://ser-mebel.uz/call-center?open=41") in buttons(
        last.reply_markup
    )


async def test_skip_note_and_preset_reminder(env):
    script(env)
    await env.text("/mijoz")
    await env.text("Laylo")
    await env.text("+998901112233")
    await env.cb("crm:src:phone")
    await env.cb("crm:note:skip")
    await env.cb("crm:rem:tomorrow")
    await env.cb("crm:save")
    assert env.backend.to("crm/leads/")[0][2]["remind"] == {"preset": "tomorrow"}
    assert env.backend.to("crm/leads/")[0][2]["note"] == ""


async def test_bad_custom_time_reasks_and_stays(env):
    script(env, parse=ServiceRefusal("Vaqtni tushunmadim", 400, "remind"))
    await env.set_state("Lead:remind_custom", name="A", phone="1", source="phone")
    await env.text("ertaga")
    assert await env.state() == "Lead:remind_custom"
    assert "Vaqtni tushunmadim" in env.session.last().text


async def test_existing_client_info_and_take_name(env):
    script(
        env,
        clients={
            "exists": True,
            "fio": "Karimov Karim",
            "invoices_count": 3,
            "open_invoice": {"id": 17, "assigned": {"id": 2, "name": "Sevara"}},
        },
    )
    await env.text("/mijoz")
    await env.text("Karim")
    await env.text("+998901234567")
    last = env.session.last()
    assert "Bazada bor" in last.text and "3 ta ariza" in last.text
    assert "#17" in last.text and "Sevara" in last.text
    assert "crm:name:client" in cbs(last.reply_markup)
    await env.cb("crm:name:client")
    await env.cb("crm:src:other")
    await env.cb("crm:note:skip")
    await env.cb("crm:rem:none")
    assert "Karimov Karim" in env.session.last().text


async def test_phone_refused_by_lookup_reasks(env):
    script(env, clients=ServiceRefusal("Telefon noto'g'ri", 400, "phone"))
    await env.text("/mijoz")
    await env.text("Karim")
    await env.text("abc")
    assert await env.state() == "Lead:phone"
    assert "Telefon noto'g'ri" in env.session.last().text


# ------------------------------------------------------------------ forward / contact
async def test_forward_prefills_name_note_and_telegram_source(env):
    script(env)
    await env.forward("Salom, divan kerak", name="Karim Aliyev", username="karim")
    assert await env.state() == "Lead:name"
    assert "crm:name:use" in cbs(env.session.last().reply_markup)
    await env.cb("crm:name:use")
    assert await env.state() == "Lead:phone"
    await env.text("+998901234567")
    kb = env.session.last().reply_markup
    assert ("✅ Telegram", "crm:src:telegram", None) in buttons(kb)  # preselected
    await env.cb("crm:src:telegram")
    note_msg = env.session.last()
    assert "@karim" in note_msg.text and "Salom, divan kerak" in note_msg.text
    await env.cb("crm:note:skip")  # keeps the prefilled note
    await env.cb("crm:rem:today")
    await env.cb("crm:save")
    body = env.backend.to("crm/leads/")[0][2]
    assert body["name"] == "Karim Aliyev"
    assert body["source"] == "telegram"
    assert body["note"] == "@karim\nSalom, divan kerak"


async def test_forward_hidden_user_and_media(env):
    await env.forward(text=None, name="Yashirin Mijoz", username=None)
    assert await env.state() == "Lead:name"
    assert "Yashirin Mijoz" in str(buttons(env.session.last().reply_markup))
    from aiogram.fsm.storage.base import StorageKey

    d = await env.dp.storage.get_data(StorageKey(env.bot.id, 555, 555))
    assert d["note"] == "[media]" and d["source"] == "telegram"


async def test_forward_note_is_clipped(env):
    await env.forward("x" * 5000)
    from aiogram.fsm.storage.base import StorageKey

    d = await env.dp.storage.get_data(StorageKey(env.bot.id, 555, 555))
    assert len(d["note"]) <= 1100


async def test_contact_prefills_phone_and_name(env):
    script(env)
    await env.contact("998901234567", "Dilshod", "Rustamov")
    assert await env.state() == "Lead:name"
    await env.cb("crm:name:use")
    kb = env.session.last().reply_markup
    assert ("📞 +998901234567", "crm:phone:use", None) in buttons(kb)
    await env.cb("crm:phone:use")
    assert env.backend.to("crm/clients/")[0][3] == {"phone": "+998901234567"}
    assert await env.state() == "Lead:source"


async def test_contact_in_phone_step_is_the_phone(env):
    script(env)
    await env.text("/mijoz")
    await env.text("Karim")
    await env.contact("+998935556677")
    assert await env.state() == "Lead:source"
    assert env.backend.to("crm/clients/")[0][3] == {"phone": "+998935556677"}


# ------------------------------------------------------------------ fall-through / not clobbered
async def test_forward_of_non_lead_adder_falls_through_to_finance(env):
    env.backend.who["crm"] = {"can_add_lead": False}
    env.backend.who["finance_member"] = {
        "id": 7, "telegram_id": 555, "name": "Jasur", "role": "staff", "is_admin": False,
        "is_active_member": True, "is_task_only": False, "has_wallet": True,
    }  # fmt: skip
    await env.forward("salom")
    assert await env.state() is None
    assert not any("Yangi mijoz" in t for t in env.session.texts())


async def test_forward_of_stranger_is_silent(env):
    env.backend.who["crm"] = {}
    await env.forward("salom")
    assert env.session.sent() == []
    assert await env.state() is None


async def test_finance_draft_is_not_clobbered(env):
    env.backend.who["finance_member"] = {
        "id": 7, "telegram_id": 555, "name": "Jasur", "role": "staff", "is_admin": False,
        "is_active_member": True, "is_task_only": False, "has_wallet": True,
    }  # fmt: skip
    await env.set_state("Tx:amount", t="expense", amount=None)
    for trigger in (env.forward, env.contact):
        await trigger()
    await env.text("/mijoz")
    await env.text("🆕 Yangi mijoz")
    assert await env.state() == "Tx:amount"
    assert not any("Yangi mijoz</b>" in t for t in env.session.texts())


async def test_hr_pending_answer_ignores_lead_state(env):
    env.backend.who["hr"] = {"employee": {"telegram_id": 555}, "is_admin": False}
    script(env)
    await env.text("/mijoz")
    await env.text("Karim")
    assert await env.state() == "Lead:phone"
    assert env.backend.to("hr/private-text/") == []


async def test_employee_without_lead_right_still_reaches_hr(env):
    env.backend.who["crm"] = {"can_add_lead": False}
    env.backend.who["hr"] = {"employee": {"telegram_id": 555}, "is_admin": False}
    await env.text("kech qolaman")
    assert len(env.backend.to("hr/private-text/")) == 1


# ------------------------------------------------------------------ save rules
async def _to_confirm(env):
    script(env)
    await env.text("/mijoz")
    await env.text("Karim")
    await env.text("+998901234567")
    await env.cb("crm:src:phone")
    await env.cb("crm:note:skip")
    await env.cb("crm:rem:none")


async def test_double_save_posts_once(env):
    await _to_confirm(env)
    await env.cb("crm:save")
    await env.cb("crm:save")
    assert len(env.backend.to("crm/leads/")) == 1
    last = env.session.answers()[-1]
    assert last.text == "Allaqachon saqlandi" and last.show_alert


async def test_save_while_saving_does_not_post(env):
    await _to_confirm(env)
    await env.set_state("Lead:saving", name="K")
    await env.cb("crm:save")
    assert env.backend.to("crm/leads/") == []
    assert env.session.answers()[-1].text == "Allaqachon saqlandi"


@pytest.mark.parametrize(
    "field,state",
    [
        ("name", "Lead:name"),
        ("phone", "Lead:phone"),
        ("source", "Lead:source"),
        ("remind", "Lead:remind"),
    ],
)
async def test_400_with_field_returns_to_that_step(env, field, state):
    await _to_confirm(env)
    env.backend.routes[("POST", "crm/leads/")] = ServiceRefusal("Xato qiymat", 400, field)
    await env.cb("crm:save")
    assert await env.state() == state
    assert "Xato qiymat" in env.session.last().text


async def test_400_without_field_returns_to_confirm_and_retry_works(env):
    await _to_confirm(env)
    env.backend.routes[("POST", "crm/leads/")] = ServiceRefusal("Ruxsat yo'q", 400)
    await env.cb("crm:save")
    assert await env.state() == "Lead:confirm"
    assert "Ruxsat yo'q" in env.session.last().text
    env.backend.routes[("POST", "crm/leads/")] = LEAD_RESPONSE
    await env.cb("crm:save")
    assert await env.state() is None
    assert len(env.backend.to("crm/leads/")) == 2


async def test_cancel_clears_only_lead_state(env):
    script(env)
    await env.text("/mijoz")
    await env.cb("crm:cancel")
    assert await env.state() is None
    await env.set_state("Tx:amount", t="expense")
    await env.cb("crm:cancel")
    assert await env.state() == "Tx:amount"


async def test_bekor_command_cancels_lead(env):
    script(env)
    await env.text("/mijoz")
    await env.text("/bekor")
    assert await env.state() is None


# ------------------------------------------------------------------ /start
async def test_start_for_lead_adder_without_roles_shows_new_button(env):
    await env.text("/start")
    m = env.session.last()
    assert "Yangi mijoz" in str(m.reply_markup) and "Ro'yxatdan" not in str(m.reply_markup)


async def test_start_for_stranger_still_gets_join_screen(env):
    env.backend.who["crm"] = {}
    await env.text("/start")
    assert "Ro'yxatdan" in str(env.session.last().reply_markup)


# ------------------------------------------------------------------ fix round
FIN_MEMBER = {
    "id": 7, "telegram_id": 555, "name": "Jasur", "role": "staff", "is_admin": False,
    "is_active_member": True, "is_task_only": False, "has_wallet": True,
}  # fmt: skip


async def test_forward_of_dual_role_user_reaches_finance(env):
    env.backend.who["finance_member"] = dict(FIN_MEMBER)
    await env.forward("chek 50000")
    assert await env.state() is None
    assert not any("Yangi mijoz" in t for t in env.session.texts())
    # ...but /mijoz and the button still start a lead
    script(env)
    await env.text("/mijoz")
    assert await env.state() == "Lead:name"


async def test_finance_member_start_hint_has_no_forward(env):
    env.backend.who["finance_member"] = dict(FIN_MEMBER)
    env.backend.routes[("GET", "finance/members/555/balance/")] = {"balance": 0, "balances": {}}
    await env.text("/start")
    assert "Yangi mijoz: /mijoz" in env.session.texts()
    assert not any("forward" in t for t in env.session.texts())


@pytest.mark.parametrize("btn", ["➖ Chiqim", "💳 Hamyonim", "🆕 Yangi mijoz"])
async def test_menu_buttons_are_not_taken_as_answers(env, btn):
    script(env)
    await env.text("/mijoz")
    await env.text(btn)
    d_state = await env.state()
    assert d_state == "Lead:name"  # the button is never taken as the name


async def test_menu_button_not_taken_as_note(env):
    await _to_confirm(env)
    await env.cb("crm:save")
    await env.text("/mijoz")
    await env.text("Karim")
    await env.text("+998901234567")
    await env.cb("crm:src:phone")
    assert await env.state() == "Lead:note"
    await env.text("➕ Kirim")
    assert await env.state() == "Lead:note"


async def test_unexpected_error_in_save_returns_to_confirm(env):
    await _to_confirm(env)
    env.backend.routes[("POST", "crm/leads/")] = RuntimeError("boom")
    await env.cb("crm:save")
    assert await env.state() == "Lead:confirm"
    env.backend.routes[("POST", "crm/leads/")] = LEAD_RESPONSE
    await env.cb("crm:save")
    assert await env.state() is None


async def test_duplicate_save_shows_info_prefix(env):
    await _to_confirm(env)
    env.backend.routes[("POST", "crm/leads/")] = {**LEAD_RESPONSE, "duplicate": True}
    await env.cb("crm:save")
    assert env.session.last().text.startswith("ℹ️ Bu ariza allaqachon yaratilgan edi")
    assert "Ariza #41" in env.session.last().text
    assert await env.state() is None


async def test_normal_save_has_no_duplicate_prefix(env):
    await _to_confirm(env)
    await env.cb("crm:save")
    assert "allaqachon" not in env.session.last().text
