"""«📕 Qarzlar»: list, add flow, pay flow, notify renderer (mocked backend, fakeredis)."""

from bot.backend.client import Conflict, Forbidden, NotFound, ServiceRefusal
from bot.finance import keyboards as K
from bot.finance import texts as T
from bot.finance.handlers import callbacks as CB
from bot.finance.handlers import menu as MN
from bot.hr.texts import FINANCE_MENU_BUTTONS

from .conftest import fx, texts


def debt(**kw):
    base = {
        "id": 1,
        "number": 12,
        "date": "2026-11-01",
        "creditor": "Do'kon Ali",
        "item": "LDSP 10 list",
        "amount": "1500000.00",
        "currency": "UZS",
        "orig_amount": None,
        "rate": None,
        "total": "1500000.00",
        "paid": "0.00",
        "remaining": "1500000.00",
        "category": {"code": "material", "name": "Material", "emoji": "🧱"},
        "order_ref": "406",
        "client": "Nazira",
        "status": "open",
        "status_label": "Ochiq",
        "closed_at": None,
        "days": 12,
        "by_name": "Jasur",
        "comment": "",
        "created_at": "2026-11-01T10:00:00Z",
        "can_pay": True,
    }
    return {**base, **kw}


def routes(be, cats):
    be.routes[("GET", "finance/categories/")] = cats
    be.routes[("GET", "finance/orders/")] = [fx("dto.order_brief.1")]
    be.routes[("GET", "finance/orders/406/")] = {"ref": "406", "client": "Nazira"}
    be.routes[("POST", "finance/parse/")] = {
        "amount": "1500000.00",
        "cur": "UZS",
        "orig": None,
        "rate": None,
    }


async def test_menu_lists_debts_with_age_icons(be, make_ctx):
    rows = [debt(days=3), debt(number=13, days=20), debt(number=14, days=40)]
    be.routes[("GET", "finance/debts/")] = {
        "rows": rows,
        "totals": {"open_count": 3, "open_uzs": "4500000.00", "open_usd": "0.00"},
    }
    ctx = make_ctx()
    await MN.on_text(ctx, "📕 Qarzlar")
    assert be.calls[-1][:2] == ("GET", "finance/debts/")
    assert be.calls[-1][3] == {"status": "open"}
    t = texts(ctx)[-1]
    assert "🟢 #12" in t and "🟡 #13" in t and "🔴 #14" in t and "qoldiq" in t
    kb = ctx.bot.send_message.call_args.kwargs["reply_markup"]
    data = [x.callback_data for r in kb.inline_keyboard for x in r]
    assert "qz:v:12" in data and "qz:n" in data and "qz:z" in data


async def test_closed_list_and_card(be, make_ctx):
    be.routes[("GET", "finance/debts/")] = {
        "rows": [debt(status="closed", days=5, closed_at="2026-11-06", remaining="0.00")],
        "totals": {},
    }
    be.routes[("GET", "finance/debts/12/")] = debt(payments=[])
    ctx = make_ctx()
    await CB.on_callback(ctx, "qz:z")
    assert be.calls[-1][3] == {"status": "closed"}
    assert "✅ #12" in texts(ctx)[-1]
    await CB.on_callback(ctx, "qz:v:12")
    assert "Qarz #12" in texts(ctx)[-1]


async def test_add_flow_posts_contract_payload_state_cleared_first(be, cats, make_ctx):
    routes(be, cats)
    seen = {}

    async def spy_state(ctx):
        seen["state"] = await ctx.st()

    def create(j, p):
        seen["body"] = j
        return debt()

    be.routes[("POST", "finance/debts/")] = create
    ctx = make_ctx()
    await CB.on_callback(ctx, "qz:n")
    assert (await ctx.st())["step"] == "qz_from"
    await MN.on_text(ctx, "Do'kon Ali")
    await MN.on_text(ctx, "LDSP 10 list")
    assert (await ctx.st())["step"] == "qz_amount"
    await MN.on_text(ctx, "1.5 mln")
    assert (await ctx.st())["step"] == "qz_cat"
    await CB.on_callback(ctx, "qz:k:material")
    assert (await ctx.st())["step"] == "qz_order"
    await CB.on_callback(ctx, "qz:o:406")
    assert (await ctx.st())["step"] == "qz_share"
    await CB.on_callback(ctx, "qz:wa")  # one extra tap on an ordinary debt
    d = await ctx.st()
    assert d["step"] == "qz_confirm"

    orig = ctx.api

    async def api(method, path, **kw):
        if path == "finance/debts/":
            await spy_state(ctx)
        return await orig(method, path, **kw)

    ctx.api = api
    await CB.on_callback(ctx, "qz:s")
    assert seen["state"] is None  # draft cleared before the POST
    assert seen["body"] == {
        "creditor": "Do'kon Ali",
        "item": "LDSP 10 list",
        "amount_text": "1.5 mln",
        "category": "material",
        "order_ref": "406",
        "comment": "",
    }
    shown = str(ctx.bot.edit_message_text.call_args_list + ctx.bot.send_message.call_args_list)
    assert "Qarz #12 yozildi" in shown
    assert await ctx.st() is None


async def test_unknown_order_id_reasks(be, cats, make_ctx):
    routes(be, cats)
    from bot.backend.client import NotFound

    be.routes[("GET", "finance/orders/999/")] = NotFound("yo'q")
    ctx = make_ctx()
    await ctx.set_st({"t": "qz", "step": "qz_ord_text", "creditor": "x", "item": "y"})
    await MN.on_text(ctx, "999")
    assert (await ctx.st())["step"] == "qz_ord_text"
    assert "topilmadi" in texts(ctx)[-1]


async def test_bad_amount_reasks(be, cats, make_ctx):
    routes(be, cats)
    be.routes[("POST", "finance/parse/")] = ServiceRefusal("x")
    ctx = make_ctx()
    await ctx.set_st({"t": "qz", "step": "qz_amount", "creditor": "x", "item": "y"})
    await MN.on_text(ctx, "abc")
    assert (await ctx.st())["step"] == "qz_amount"
    assert "tushunmadim" in texts(ctx)[-1]


async def test_pay_full_flow(be, make_ctx):
    be.routes[("GET", "finance/debts/12/")] = debt()
    res = {
        "debt": debt(status="closed", remaining="0.00", days=12),
        "operation": fx("dto.operation.1"),
        "balance": "1000.00",
    }
    be.routes[("POST", "finance/debts/12/pay/")] = res
    ctx = make_ctx()
    await CB.on_callback(ctx, "qz:p:12")
    assert (await ctx.st())["step"] == "qz_pay_amount"
    await CB.on_callback(ctx, _pay_btn(ctx, "qz:pf"))
    assert (await ctx.st())["step"] == "qz_pay_confirm"
    await CB.on_callback(ctx, _pay_btn(ctx, "qz:py"))
    assert await ctx.st() is None
    method, path, body, _ = be.calls[-1]
    assert (method, path, body) == ("POST", "finance/debts/12/pay/", {"amount_text": None})
    shown = str(ctx.bot.edit_message_text.call_args_list + ctx.bot.send_message.call_args_list)
    assert "to'liq yopildi" in shown


async def test_pay_typed_amount_and_currency_check(be, make_ctx):
    be.routes[("GET", "finance/debts/12/")] = debt()
    be.routes[("POST", "finance/parse/")] = {
        "amount": "500000.00",
        "cur": "UZS",
        "orig": None,
        "rate": None,
    }
    be.routes[("POST", "finance/debts/12/pay/")] = {
        "debt": debt(remaining="1000000.00"),
        "operation": fx("dto.operation.1"),
        "balance": "-5.00",
    }
    ctx = make_ctx()
    await CB.on_callback(ctx, "qz:p:12")
    await MN.on_text(ctx, "500000")
    assert (await ctx.st())["step"] == "qz_pay_confirm"
    await CB.on_callback(ctx, _pay_btn(ctx, "qz:py"))
    assert be.calls[-1][2] == {"amount_text": "500000"}
    assert "Qoldiq" in str(
        ctx.bot.edit_message_text.call_args_list + ctx.bot.send_message.call_args_list
    )
    assert "manfiy" in texts(ctx)[-1]

    # a USD debt refuses a so'm amount before anything is booked
    be.routes[("GET", "finance/debts/13/")] = debt(number=13, currency="USD", remaining="300.00")
    await CB.on_callback(ctx, "qz:p:13")
    await MN.on_text(ctx, "500000")
    assert (await ctx.st())["step"] == "qz_pay_amount"
    assert "$" in texts(ctx)[-1]


async def test_pay_conflict_shows_already_paid(be, make_ctx):
    be.routes[("POST", "finance/debts/12/pay/")] = Conflict("x")
    ctx = make_ctx()
    await ctx.set_st({"t": "qz", "step": "qz_pay_confirm", "n": 12, "amount_text": None})
    await ctx.load()
    await CB.on_callback(ctx, "qz:py")
    shown = str(ctx.bot.edit_message_text.call_args_list + ctx.bot.send_message.call_args_list)
    assert "allaqachon" in shown
    assert await ctx.st() is None


async def test_pay_not_allowed(be, make_ctx):
    be.routes[("GET", "finance/debts/12/")] = debt(can_pay=False)
    ctx = make_ctx()
    await CB.on_callback(ctx, "qz:p:12")
    assert await ctx.st() is None
    assert "hamyon" in texts(ctx)[-1]


async def test_buttons_without_matching_step_are_ignored(be, make_ctx):
    ctx = make_ctx()
    for arg in ("s", "py", "pf", "k:material", "o:406", "ot", "wa", "sb", "x:1"):
        await CB.on_callback(ctx, f"qz:{arg}")
    assert be.calls == [] and texts(ctx) == []
    await ctx.set_st({"t": "qz", "step": "qz_from"})
    await ctx.load()
    for arg in ("s", "py", "pf", "k:material", "o:406", "ot", "wa", "sb", "x:1"):
        await CB.on_callback(ctx, f"qz:{arg}")
    assert be.calls == [] and (await ctx.st())["step"] == "qz_from"


def test_menu_buttons_registered():
    assert "📕 Qarzlar" in FINANCE_MENU_BUTTONS
    assert FINANCE_MENU_BUTTONS >= set(MN.MENU_STAFF) | set(MN.MENU_ADMIN)
    assert ["📕 Qarzlar"] in [[k.text for k in r] for r in T.KB_STAFF.keyboard]
    assert "📕 Qarzlar" in [k.text for r in T.KB_ADMIN.keyboard for k in r]


def test_callback_data_within_64_bytes():
    ref = "A" * 32
    kb = K.debt_order_kb([{"ref": ref, "client": "X" * 40, "bucket": "yangi"}])
    for r in kb.inline_keyboard:
        for x in r:
            assert len(x.callback_data.encode()) <= 64
    assert len(f"qz:o:{ref}".encode()) <= 64


async def test_list_is_paginated_and_totals_first(be, make_ctx):
    rows = [debt(number=i, days=i) for i in range(1, 46)]
    be.routes[("GET", "finance/debts/")] = {
        "rows": rows,
        "totals": {"open_count": 45, "open_uzs": "9000000.00", "open_usd": "0.00"},
    }
    ctx = make_ctx()
    seen = set()
    for arg in ("qz:l", "qz:l:1", "qz:l:2"):
        await CB.on_callback(ctx, arg)
        t = texts(ctx)[-1]
        assert t.index("Jami qoldiq") < t.index("#")
        kb = ctx.bot.send_message.call_args.kwargs["reply_markup"]
        data = [x.callback_data for r in kb.inline_keyboard for x in r]
        seen |= {int(x.split(":")[2]) for x in data if x.startswith("qz:v:")}
        if arg == "qz:l":
            assert "qz:l:1" in data and "qz:l:-1" not in data
        if arg == "qz:l:2":
            assert "qz:l:1" in data and "qz:l:3" not in data
    assert seen == set(range(1, 46))


async def test_wallet_less_member_cannot_start_add(be, make_ctx):
    ctx = make_ctx(member={"has_wallet": False})
    await CB.on_callback(ctx, "qz:n")
    assert await ctx.st() is None
    assert "hamyon" in texts(ctx)[-1]
    ctx = make_ctx(member={"has_wallet": False}, admin=True)
    await CB.on_callback(ctx, "qz:n")
    assert (await ctx.st())["step"] == "qz_from"


# ---------------------------------------------------------------- delete (can_delete)
def cb_data(kb):
    return [x.callback_data for r in kb.inline_keyboard for x in r]


def last_kb(ctx):
    return ctx.bot.send_message.call_args.kwargs["reply_markup"]


def test_card_kb_offers_delete_only_when_can_delete():
    assert "qz:d:12" in cb_data(K.debt_card_kb(debt(can_delete=True)))
    assert "qz:d:12" not in cb_data(K.debt_card_kb(debt(can_delete=False)))
    assert "qz:d:12" not in cb_data(K.debt_card_kb(debt()))  # flag missing = no button


async def test_saved_card_offers_delete_from_create_response(be, cats, make_ctx):
    routes(be, cats)
    be.routes[("POST", "finance/debts/")] = debt(can_delete=True)
    ctx = make_ctx()
    await ctx.set_st(
        {
            "t": "qz",
            "step": "qz_confirm",
            "creditor": "Do'kon",
            "item": "LDSP",
            "amount_text": "1.5 mln",
            "cat": "material",
            "ord": "406",
        }
    )
    await ctx.load()
    await CB.on_callback(ctx, "qz:s")
    assert "qz:d:12" in cb_data(last_kb(ctx))


async def test_ask_delete_confirms_without_deleting(be, make_ctx):
    be.routes[("GET", "finance/debts/12/")] = debt(can_delete=True)
    ctx = make_ctx()
    await CB.on_callback(ctx, "qz:d:12")
    assert [c[:2] for c in be.calls] == [("GET", "finance/debts/12/")]
    assert "o'chirilsinmi" in texts(ctx)[-1] and "Qarz #12" in texts(ctx)[-1]
    assert cb_data(last_kb(ctx)) == ["qz:dy:12", "qz:v:12"]


async def test_ask_delete_without_permission_shows_card_with_note(be, make_ctx):
    be.routes[("GET", "finance/debts/12/")] = debt(can_delete=False, paid="1.00")
    ctx = make_ctx()
    await CB.on_callback(ctx, "qz:d:12")
    assert "to'lov yozilgan" in texts(ctx)[-1]
    assert "qz:dy:12" not in cb_data(last_kb(ctx))
    assert all(c[0] == "GET" for c in be.calls)


async def test_confirm_calls_delete_once(be, make_ctx):
    be.routes[("DELETE", "finance/debts/12/")] = None
    ctx = make_ctx()
    await CB.on_callback(ctx, "qz:dy:12")
    assert [c[:2] for c in be.calls] == [("DELETE", "finance/debts/12/")]
    assert "Qarz #12 o'chirildi" in texts(ctx)[-1]
    assert cb_data(last_kb(ctx)) == ["qz:l"]


async def test_delete_404_says_already_gone(be, make_ctx):
    be.routes[("DELETE", "finance/debts/12/")] = NotFound("x", 404)
    be.routes[("GET", "finance/debts/12/")] = NotFound("x", 404)
    for arg in ("qz:dy:12", "qz:d:12"):
        ctx = make_ctx()
        await CB.on_callback(ctx, arg)
        assert "allaqachon o'chirilgan" in texts(ctx)[-1]
        assert cb_data(last_kb(ctx)) == ["qz:l"]


async def test_delete_409_and_403_show_backend_detail_with_back_button(be, make_ctx):
    for exc, detail in (
        (Conflict("Qarzga to'lov yozilgan.", 409), "to'lov yozilgan"),
        (Forbidden("Ruxsat yo'q.", 403), "Ruxsat yo'q"),
    ):
        be.routes[("DELETE", "finance/debts/12/")] = exc
        ctx = make_ctx()
        await CB.on_callback(ctx, "qz:dy:12")
        assert detail in texts(ctx)[-1]
        assert cb_data(last_kb(ctx)) == ["qz:v:12"]


async def test_draft_survives_delete_prompt_and_no(be, make_ctx):
    be.routes[("GET", "finance/debts/12/")] = debt(can_delete=True)
    ctx = make_ctx()
    draft = {"t": "qz", "step": "qz_confirm", "creditor": "X", "item": "Y"}
    await ctx.set_st(dict(draft))
    await ctx.load()
    await CB.on_callback(ctx, "qz:d:12")
    assert await ctx.st() == draft
    assert "qz:v:12" in cb_data(last_kb(ctx))  # «Yo'q» is not the shared cancel
    assert "cancel" not in cb_data(last_kb(ctx))
    be.routes[("GET", "finance/debts/12/")] = debt(can_delete=True, payments=[])
    await CB.on_callback(ctx, "qz:v:12")
    assert await ctx.st() == draft
    assert "Qarz #12" in texts(ctx)[-1]


async def test_non_digit_delete_callbacks_make_no_call(be, make_ctx):
    ctx = make_ctx()
    for arg in ("qz:d:abc", "qz:dy:abc", "qz:d:", "qz:dy"):
        await CB.on_callback(ctx, arg)
    await ctx.set_st({"t": "qz", "step": "qz_from"})
    await ctx.load()
    for arg in ("qz:d:abc", "qz:dy:abc"):
        await CB.on_callback(ctx, arg)
    assert be.calls == [] and texts(ctx) == []
    assert (await ctx.st())["step"] == "qz_from"


def test_delete_callback_data_within_64_bytes():
    n = 10**12
    for kb in (
        K.debt_card_kb(debt(number=n, can_delete=True)),
        K.debt_delete_kb(n),
        K.debt_back_kb(n),
        K.debt_gone_kb(),
    ):
        for data in cb_data(kb):
            assert len(data.encode()) <= 64


# ================================================================ split over several orders
ORDERS = {"406": "Nazira", "407": "Bobur", "408": "Dilnoza"}


def parse_route(j, p):
    t = j["text"]
    if t.endswith("$"):
        v = float(t[:-1])
        return {"amount": f"{v * 12000:.2f}", "cur": "USD", "orig": f"{v:.2f}", "rate": "12000"}
    v = float(t)
    return {"amount": f"{v:.2f}", "cur": "UZS", "orig": None, "rate": None}


def split_routes(be, cats):
    routes(be, cats)
    be.routes[("GET", "finance/orders/")] = [
        {"ref": r, "client": c, "bucket": "yangi"} for r, c in ORDERS.items()
    ]
    for r, c in ORDERS.items():
        be.routes[("GET", f"finance/orders/{r}/")] = {"ref": r, "client": c}
    be.routes[("POST", "finance/parse/")] = parse_route


async def start_split(be, cats, make_ctx, amount="100$", total_text="100$"):
    split_routes(be, cats)
    ctx = make_ctx()
    await ctx.set_st({"t": "qz", "step": "qz_amount", "creditor": "Do'kon", "item": "Furnitura"})
    await ctx.load()
    await MN.on_text(ctx, total_text)
    await CB.on_callback(ctx, "qz:k:material")
    return ctx


def shown(ctx):
    return str(ctx.bot.edit_message_text.call_args_list + ctx.bot.send_message.call_args_list)


def kb_data(ctx):
    return cb_data(last_kb(ctx))


async def test_split_flow_posts_exact_allocations(be, cats, make_ctx):
    ctx = await start_split(be, cats, make_ctx)
    d = await ctx.st()
    assert (d["cur"], d["tot"], d["al"]) == ("USD", "100.00", [])
    assert "qz:o:406" in kb_data(ctx)

    await CB.on_callback(ctx, "qz:o:406")
    assert (await ctx.st())["step"] == "qz_share"
    assert "Qoldi: <b>100.00 $</b>" in texts(ctx)[-1]
    await MN.on_text(ctx, "20$")
    d = await ctx.st()
    assert d["step"] == "qz_order" and [r["a"] for r in d["al"]] == ["20.00"]
    t = texts(ctx)[-1]
    assert "406 Nazira — 20.00 $" in t and "Qoldi: <b>80.00 $</b>" in t
    data = kb_data(ctx)
    assert "qz:o:406" not in data and "qz:o:407" in data and "qz:x:1" in data

    await CB.on_callback(ctx, "qz:o:407")
    await MN.on_text(ctx, "30$")
    assert "Qoldi: <b>50.00 $</b>" in texts(ctx)[-1]
    await CB.on_callback(ctx, "qz:o:408")
    assert any(x.startswith("qz:wa") for x in kb_data(ctx))
    assert "50.00 $" in str(ctx.bot.send_message.call_args)
    await CB.on_callback(ctx, "qz:wa")
    d = await ctx.st()
    assert d["step"] == "qz_confirm"
    t = texts(ctx)[-1]
    assert all(x in t for x in ("406 Nazira", "407 Bobur", "408 Dilnoza", "50.00 $"))
    assert {"qz:x:1", "qz:x:2", "qz:x:3", "qz:s", "cancel"} <= set(kb_data(ctx))

    seen = {}

    def create(j, p):
        seen["body"] = j
        return debt()

    be.routes[("POST", "finance/debts/")] = create
    await CB.on_callback(ctx, "qz:s")
    assert seen["body"] == {
        "creditor": "Do'kon",
        "item": "Furnitura",
        "amount_text": "100$",
        "category": "material",
        "allocations": [
            {"ref": "406", "amount": "20.00"},
            {"ref": "407", "amount": "30.00"},
            {"ref": "408", "amount": "50.00"},
        ],
        "comment": "",
    }
    assert "order_ref" not in seen["body"]
    assert await ctx.st() is None


async def test_split_uzs_share_equal_to_remainder_goes_to_confirm(be, cats, make_ctx):
    ctx = await start_split(be, cats, make_ctx, total_text="1000000")
    await CB.on_callback(ctx, "qz:o:406")
    await MN.on_text(ctx, "400000")
    await CB.on_callback(ctx, "qz:o:407")
    await MN.on_text(ctx, "600000")  # exactly the remainder
    d = await ctx.st()
    assert d["step"] == "qz_confirm" and len(d["al"]) == 2


async def test_split_share_above_remainder_and_wrong_currency_refused(be, cats, make_ctx):
    ctx = await start_split(be, cats, make_ctx)
    await CB.on_callback(ctx, "qz:o:406")
    await MN.on_text(ctx, "150$")
    d = await ctx.st()
    assert d["step"] == "qz_share" and d["al"] == []
    assert "oshib" in texts(ctx)[-1] and "100.00 $" in texts(ctx)[-1]
    await MN.on_text(ctx, "50000")  # so'm on a dollar debt
    assert "$" in texts(ctx)[-1] and (await ctx.st())["al"] == []
    await MN.on_text(ctx, "0$")
    assert (await ctx.st())["al"] == []

    ctx = await start_split(be, cats, make_ctx, total_text="1000000")
    await CB.on_callback(ctx, "qz:o:406")
    await MN.on_text(ctx, "20$")
    assert "so'm" in texts(ctx)[-1] and (await ctx.st())["al"] == []
    be.routes[("POST", "finance/parse/")] = ServiceRefusal("x")
    await MN.on_text(ctx, "abc")
    assert "tushunmadim" in texts(ctx)[-1]


async def test_split_duplicate_order_reasks_for_button_and_typed(be, cats, make_ctx):
    ctx = await start_split(be, cats, make_ctx)
    await CB.on_callback(ctx, "qz:o:406")
    await MN.on_text(ctx, "20$")
    await CB.on_callback(ctx, "qz:o:406")  # a stale button of the same ID
    assert (await ctx.st())["step"] == "qz_order" and len((await ctx.st())["al"]) == 1
    assert any("allaqachon" in t for t in texts(ctx))
    await CB.on_callback(ctx, "qz:ot")
    assert (await ctx.st())["step"] == "qz_ord_text"
    await MN.on_text(ctx, "#406")
    assert (await ctx.st())["step"] == "qz_order"
    await CB.on_callback(ctx, "qz:ot")
    await MN.on_text(ctx, "407")
    assert (await ctx.st())["step"] == "qz_share" and (await ctx.st())["cr"]["r"] == "407"


async def test_split_other_id_button_goes_back_without_a_row(be, cats, make_ctx):
    ctx = await start_split(be, cats, make_ctx)
    await CB.on_callback(ctx, "qz:o:406")
    await CB.on_callback(ctx, "qz:sb")
    d = await ctx.st()
    assert d["step"] == "qz_order" and d["al"] == [] and "cr" not in d
    assert "qz:o:406" in kb_data(ctx)


async def test_split_tenth_row_accepts_only_the_whole_remainder(be, cats, make_ctx):
    ctx = await start_split(be, cats, make_ctx, total_text="1000")
    d = await ctx.st()
    d["al"] = [{"i": i, "r": f"A{i}", "c": "", "a": "10.00"} for i in range(1, 10)]
    d["nx"] = 10
    await ctx.set_st(d)
    await ctx.load()
    be.routes[("GET", "finance/orders/406/")] = {"ref": "406", "client": "Nazira"}
    await CB.on_callback(ctx, "qz:o:406")
    assert "Oxirgi ID" in texts(ctx)[-1]
    await MN.on_text(ctx, "10")
    assert (await ctx.st())["step"] == "qz_share" and len((await ctx.st())["al"]) == 9
    assert "Hammasi" in texts(ctx)[-1]
    await CB.on_callback(ctx, "qz:wa")
    d = await ctx.st()
    assert d["step"] == "qz_confirm" and len(d["al"]) == 10 and d["al"][-1]["a"] == "910.00"
    assert len([x for x in kb_data(ctx) if x.startswith("qz:x:")]) == 10
    assert len(kb_data(ctx)) <= 100


async def test_split_remove_row_from_picker_and_confirm_restores_remainder(be, cats, make_ctx):
    ctx = await start_split(be, cats, make_ctx)
    for ref, amt in (("406", "20$"), ("407", "30$")):
        await CB.on_callback(ctx, f"qz:o:{ref}")
        await MN.on_text(ctx, amt)
    assert "Qoldi: <b>50.00 $</b>" in texts(ctx)[-1]
    await CB.on_callback(ctx, "qz:x:1")  # from the picker
    d = await ctx.st()
    assert [r["r"] for r in d["al"]] == ["407"] and d["step"] == "qz_order"
    assert "Qoldi: <b>70.00 $</b>" in texts(ctx)[-1] and "qz:o:406" in kb_data(ctx)
    await CB.on_callback(ctx, "qz:o:406")
    await CB.on_callback(ctx, "qz:wa")
    assert (await ctx.st())["step"] == "qz_confirm"
    await CB.on_callback(ctx, "qz:x:2")  # from the confirm card; row ids are never reused
    d = await ctx.st()
    assert d["step"] == "qz_order"
    assert [(r["i"], r["r"]) for r in d["al"]] == [(3, "406")] and d["nx"] == 4
    assert "Qoldi: <b>30.00 $</b>" in texts(ctx)[-1]


async def test_split_stale_or_bad_remove_callbacks_are_ignored(be, cats, make_ctx):
    ctx = await start_split(be, cats, make_ctx)
    await CB.on_callback(ctx, "qz:o:406")
    await MN.on_text(ctx, "20$")
    before = await ctx.st()
    n_calls = len(be.calls)
    for arg in ("qz:x:99", "qz:x:abc", "qz:x:", "qz:x:1:2", "qz:x:-1"):
        await CB.on_callback(ctx, arg)
    assert await ctx.st() == before and len(be.calls) == n_calls


async def test_split_cancel_at_every_step_clears_the_draft(be, cats, make_ctx):
    for upto in ("amount", "order", "share", "after_row", "confirm"):
        ctx = await start_split(be, cats, make_ctx)
        if upto in ("share", "after_row", "confirm"):
            await CB.on_callback(ctx, "qz:o:406")
        if upto == "after_row":
            await MN.on_text(ctx, "20$")
        if upto == "confirm":
            await CB.on_callback(ctx, "qz:wa")
        assert await ctx.st() is not None
        await CB.on_callback(ctx, "cancel")
        assert await ctx.st() is None, upto


async def test_split_pre_deploy_drafts_continue_as_single_order(be, cats, make_ctx):
    routes(be, cats)
    ctx = make_ctx()
    old = {
        "t": "qz",
        "step": "qz_order",
        "creditor": "X",
        "item": "Y",
        "amount_text": "1.5 mln",
        "preview": "1 500 000 so'm",
        "cat": "material",
        "cat_label": "Material",
    }
    await ctx.set_st(dict(old))
    await ctx.load()
    await CB.on_callback(ctx, "qz:o:406")  # no cur/al: straight to the confirm card
    d = await ctx.st()
    assert d["step"] == "qz_confirm" and d["ord"] == "406" and "al" not in d
    assert "Nazira" in texts(ctx)[-1]
    be.routes[("POST", "finance/debts/")] = debt()
    await CB.on_callback(ctx, "qz:s")
    assert be.calls[-1][2] == {
        "creditor": "X",
        "item": "Y",
        "amount_text": "1.5 mln",
        "category": "material",
        "order_ref": "406",
        "comment": "",
    }
    # an old draft waiting for the typed ID
    await ctx.set_st({**old, "step": "qz_ord_text"})
    await ctx.load()
    await MN.on_text(ctx, "406")
    assert (await ctx.st())["step"] == "qz_confirm"


async def test_split_post_400_restores_the_draft_at_confirm(be, cats, make_ctx):
    ctx = await start_split(be, cats, make_ctx)
    await CB.on_callback(ctx, "qz:o:406")
    await MN.on_text(ctx, "20$")
    await CB.on_callback(ctx, "qz:o:407")
    await CB.on_callback(ctx, "qz:wa")
    be.routes[("POST", "finance/debts/")] = ServiceRefusal("Buyurtma topilmadi")
    full = await ctx.st()
    await CB.on_callback(ctx, "qz:s")
    d = await ctx.st()
    assert d["step"] == "qz_confirm" and d["al"] == full["al"]
    assert any("Buyurtma topilmadi" in t for t in texts(ctx))
    assert "qz:s" in kb_data(ctx)
    # a 400 on an ordinary debt keeps the draft too
    be.routes[("POST", "finance/debts/")] = debt()
    await CB.on_callback(ctx, "qz:s")
    assert await ctx.st() is None


async def test_split_draft_is_cleared_before_the_post(be, cats, make_ctx):
    ctx = await start_split(be, cats, make_ctx)
    await CB.on_callback(ctx, "qz:o:406")
    await MN.on_text(ctx, "20$")
    await CB.on_callback(ctx, "qz:o:407")
    await CB.on_callback(ctx, "qz:wa")
    seen = {}

    def create(j, p):
        return debt()

    be.routes[("POST", "finance/debts/")] = create
    orig = ctx.api

    async def api(method, path, **kw):
        if path == "finance/debts/":
            seen["state"] = await ctx.st()
        return await orig(method, path, **kw)

    ctx.api = api
    await CB.on_callback(ctx, "qz:s")
    assert seen["state"] is None


# ---------------------------------------------------------------- split: texts
def split_debt(**kw):
    als = [
        {
            "id": 7,
            "order_ref": "406",
            "client": "Nazira",
            "amount": "20.00",
            "paid": "4.00",
            "remaining": "16.00",
        },
        {
            "id": 8,
            "order_ref": "407",
            "client": "Bobur",
            "amount": "30.00",
            "paid": "0.00",
            "remaining": "30.00",
        },
        {
            "id": 9,
            "order_ref": "408",
            "client": "Dilnoza",
            "amount": "50.00",
            "paid": "50.00",
            "remaining": "0.00",
        },
        {
            "id": 10,
            "order_ref": "409",
            "client": "",
            "amount": "1.00",
            "paid": "0.00",
            "remaining": "1.00",
        },
        {
            "id": 11,
            "order_ref": "410",
            "client": "",
            "amount": "1.00",
            "paid": "0.00",
            "remaining": "1.00",
        },
    ]
    base = {
        "currency": "USD",
        "total": "102.00",
        "paid": "54.00",
        "remaining": "48.00",
        "order_ref": "406, 407, 408 +2",
        "client": "",
        "allocations": als,
    }
    return debt(**{**base, **kw})


def test_split_list_line_card_and_draft_render():
    line = T.debt_line(split_debt())
    assert "🧾 406: 20.00 $ · 407: 30.00 $ · 408: 50.00 $ +2" in line
    assert "qoldiq 48.00 $" in line
    card = T.debt_card(
        split_debt(
            payments=[
                {
                    "number": 241,
                    "date": "2026-11-02",
                    "amount": "48000.00",
                    "currency": "USD",
                    "orig_amount": "4.00",
                    "order_ref": "406",
                    "member": {"name": "Jasur"},
                }
            ]
        )
    )
    assert "• 406 Nazira — 20.00 $ (to'langan 4.00 $)" in card
    assert "• 407 Bobur — 30.00 $" in card and "407 Bobur — 30.00 $ (" not in card
    assert "#241" in card and "🧾 406" in card.split("To'lovlar")[1]
    draft = T.debt_draft_card(
        {
            "creditor": "X",
            "item": "Y",
            "preview": "100 USD",
            "cat_label": "M",
            "cur": "USD",
            "tot": "100.00",
            "al": [
                {"i": 1, "r": "406", "c": "Nazira", "a": "40.00"},
                {"i": 2, "r": "407", "c": "", "a": "60.00"},
            ],
        }
    )
    assert "• 406 Nazira — 40.00 $" in draft and "• 407 — 60.00 $" in draft


def test_old_backend_without_allocations_falls_back_to_display_text():
    d = debt(order_ref="406, 407 +1", client="")
    assert "🧾 406, 407 +1" in T.debt_line(d)
    assert "🧾 406, 407 +1" in T.debt_card(d)
    assert "Buyurtmalar" not in T.debt_card(d)
    one = debt(
        allocations=[
            {
                "id": 1,
                "order_ref": "406",
                "client": "Nazira",
                "amount": "1500000.00",
                "paid": "0.00",
                "remaining": "1500000.00",
            }
        ]
    )
    assert "Buyurtmalar" not in T.debt_card(one) and "🧾 406 Nazira" in T.debt_line(one)


# ---------------------------------------------------------------- split: pay flow
async def test_split_pay_picker_lists_only_unpaid_orders(be, make_ctx):
    be.routes[("GET", "finance/debts/12/")] = split_debt()
    ctx = make_ctx()
    await CB.on_callback(ctx, "qz:p:12")
    assert await ctx.st() is None  # no FSM step: the picker is stateless
    data = kb_data(ctx)
    assert data == ["qz:po:12:7", "qz:po:12:8", "qz:po:12:10", "qz:po:12:11", "qz:pw:12", "qz:v:12"]
    labels = [x.text for r in last_kb(ctx).inline_keyboard for x in r]
    assert labels[0] == "🧾 406 — qoldiq 16.00 $" and labels[4] == "✅ Hammasi: 48.00 $"
    assert all("408" not in x for x in labels)


async def test_split_pay_chosen_order_sends_allocation(be, make_ctx):
    be.routes[("GET", "finance/debts/12/")] = split_debt()
    op = {**fx("dto.operation.1"), "order_ref": "406", "currency": "USD", "orig_amount": "4.00"}
    be.routes[("POST", "finance/debts/12/pay/")] = {
        "debt": split_debt(),
        "operation": op,
        "operations": [op],
        "balance": "10.00",
    }
    ctx = make_ctx()
    await CB.on_callback(ctx, "qz:po:12:7")
    d = await ctx.st()
    assert d["step"] == "qz_pay_amount" and d["alloc"] == 7 and d["rem_text"] == "16.00 $"
    assert "406" in texts(ctx)[-1] and "16.00 $" in texts(ctx)[-1]
    be.routes[("POST", "finance/parse/")] = parse_route
    await MN.on_text(ctx, "4$")
    await CB.on_callback(ctx, _pay_btn(ctx, "qz:py"))
    assert be.calls[-1][:3] == (
        "POST",
        "finance/debts/12/pay/",
        {"amount_text": "4$", "allocation": 7},
    )
    assert all(x in shown(ctx) for x in ("🧾 406", "4.00 $", "Qoldiq"))

    # «to'liq» of that order, with the allocation
    await CB.on_callback(ctx, "qz:po:12:7")
    await CB.on_callback(ctx, _pay_btn(ctx, "qz:pf"))
    await CB.on_callback(ctx, _pay_btn(ctx, "qz:py"))
    assert be.calls[-1][2] == {"amount_text": None, "allocation": 7}


async def test_split_pay_hammasi_sends_no_allocation_and_lists_every_op(be, make_ctx):
    be.routes[("GET", "finance/debts/12/")] = split_debt()
    ops = [
        {
            **fx("dto.operation.1"),
            "number": 241,
            "order_ref": "406",
            "currency": "USD",
            "orig_amount": "16.00",
        },
        {
            **fx("dto.operation.1"),
            "number": 242,
            "order_ref": "407",
            "currency": "USD",
            "orig_amount": "30.00",
        },
    ]
    be.routes[("POST", "finance/debts/12/pay/")] = {
        "debt": split_debt(status="closed", remaining="0.00", days=3),
        "operation": ops[0],
        "operations": ops,
        "balance": "5.00",
    }
    ctx = make_ctx()
    await CB.on_callback(ctx, "qz:pw:12")
    assert (await ctx.st())["step"] == "qz_pay_confirm"
    await CB.on_callback(ctx, _pay_btn(ctx, "qz:py"))
    assert be.calls[-1][:3] == ("POST", "finance/debts/12/pay/", {"amount_text": None})
    assert "to'liq yopildi" in shown(ctx) and "#241 · 🧾 406 · 16.00 $" in shown(ctx)
    assert "#242 · 🧾 407 · 30.00 $" in shown(ctx)


async def test_split_pay_stale_button_shows_detail_and_card(be, make_ctx):
    # the allocation was paid meanwhile: the fresh debt no longer lists it
    be.routes[("GET", "finance/debts/12/")] = split_debt()
    ctx = make_ctx()
    await CB.on_callback(ctx, "qz:po:12:9")
    assert await ctx.st() is None and "qoldiq yo'q" in "".join(texts(ctx))
    assert "Qarz #12" in texts(ctx)[-1]  # back on the card
    await CB.on_callback(ctx, "qz:po:12:999")
    assert await ctx.st() is None and texts(ctx).count(texts(ctx)[-1]) >= 1
    assert "".join(texts(ctx)).count("qoldiq yo'q") == 2
    # the backend refuses at the POST (stale): detail + card, nothing else
    be.routes[("POST", "finance/debts/12/pay/")] = ServiceRefusal("Bu buyurtma to'langan")
    await CB.on_callback(ctx, "qz:po:12:7")
    await CB.on_callback(ctx, _pay_btn(ctx, "qz:pf"))
    await CB.on_callback(ctx, _pay_btn(ctx, "qz:py"))
    assert await ctx.st() is None and "Bu buyurtma to'langan" in texts(ctx)[-1]
    assert "Qarz #12" in shown(ctx)
    # non-digit pieces make no call
    n = len(be.calls)
    for arg in ("qz:po:x:7", "qz:po:12", "qz:po:12:x", "qz:pw:x"):
        await CB.on_callback(ctx, arg)
    assert len(be.calls) == n


async def test_pay_single_order_debt_is_unchanged_even_with_one_allocation(be, make_ctx):
    one = [
        {
            "id": 1,
            "order_ref": "406",
            "client": "Nazira",
            "amount": "1500000.00",
            "paid": "0.00",
            "remaining": "1500000.00",
        }
    ]
    be.routes[("GET", "finance/debts/12/")] = debt(allocations=one)
    op = fx("dto.operation.1")
    be.routes[("POST", "finance/debts/12/pay/")] = {
        "debt": debt(status="closed", remaining="0.00", allocations=one),
        "operation": op,
        "operations": [op],
        "balance": "1.00",
    }
    ctx = make_ctx()
    await CB.on_callback(ctx, "qz:p:12")
    assert (await ctx.st())["step"] == "qz_pay_amount" and "alloc" not in await ctx.st()
    await CB.on_callback(ctx, _pay_btn(ctx, "qz:pf"))
    await CB.on_callback(ctx, _pay_btn(ctx, "qz:py"))
    assert be.calls[-1][2] == {"amount_text": None}
    assert f"Chiqim #{op['number']}" in shown(ctx)


async def test_pay_result_without_operations_key_falls_back_to_operation(be, make_ctx):
    be.routes[("GET", "finance/debts/12/")] = split_debt()
    op = {**fx("dto.operation.1"), "order_ref": "406", "currency": "USD", "orig_amount": "16.00"}
    be.routes[("POST", "finance/debts/12/pay/")] = {
        "debt": split_debt(),
        "operation": op,
        "balance": "1.00",
    }
    ctx = make_ctx()
    await CB.on_callback(ctx, "qz:po:12:7")
    await CB.on_callback(ctx, _pay_btn(ctx, "qz:pf"))
    await CB.on_callback(ctx, _pay_btn(ctx, "qz:py"))
    assert f"#{op['number']} · 🧾 406 · 16.00 $" in shown(ctx)


# ---------------------------------------------------------------- split: limits
def test_split_callback_data_and_button_counts_within_limits():
    long_ref = "Я" * 30  # 60 bytes: `qz:o:` + ref no longer fits 64 BYTES
    orders = [{"ref": f"{i}", "client": "Ж" * 40, "bucket": "yangi"} for i in range(60)]
    orders = orders[:58] + [
        {"ref": long_ref, "client": "x", "bucket": "yangi"},
        {"ref": "A" * 32, "client": "x", "bucket": "yangi"},
    ]
    rows = [{"i": i, "r": long_ref, "c": "Ж" * 28, "a": "1.00"} for i in range(1, 11)]
    for kb in (
        K.debt_order_kb(orders, rows),
        K.debt_confirm_kb(rows),
        K.debt_share_kb("1 000 000 so'm"),
        K.debt_pay_order_kb(split_debt(number=10**12), "48.00 $"),
    ):
        data = cb_data(kb)
        assert all(len(x.encode()) <= 64 for x in data)
        assert len(data) <= 100
    picker = cb_data(K.debt_order_kb(orders, rows))
    assert f"qz:o:{long_ref}" not in picker  # omitted, can still be typed
    assert "qz:o:" + "A" * 32 in picker
    assert len([x for x in picker if x.startswith("qz:x:")]) == 10
    assert len(picker) <= 60 + 10 + 2


# ---------------------------------------------------------------- stale pay buttons
def _pay_btn(ctx, prefix):
    """The pay button of the LAST message sent, e.g. «qz:py:ab12cd34»."""
    return next(x for x in kb_data(ctx) if x.startswith(prefix))


async def test_stale_pay_confirm_button_cannot_book_another_order(be, make_ctx):
    be.routes[("GET", "finance/debts/12/")] = split_debt()
    be.routes[("POST", "finance/parse/")] = parse_route
    op = {**fx("dto.operation.1"), "order_ref": "407", "currency": "USD", "orig_amount": "30.00"}
    be.routes[("POST", "finance/debts/12/pay/")] = {
        "debt": split_debt(),
        "operation": op,
        "operations": [op],
        "balance": "1.00",
    }
    ctx = make_ctx()
    await CB.on_callback(ctx, "qz:p:12")  # the picker stays live
    await CB.on_callback(ctx, "qz:po:12:7")  # 406
    await MN.on_text(ctx, "4$")
    m1 = _pay_btn(ctx, "qz:py")  # M1: 4 $, 406
    assert m1.startswith("qz:py:") and len(m1.encode()) <= 64
    await CB.on_callback(ctx, "qz:po:12:8")  # 407 from the same picker
    pf = _pay_btn(ctx, "qz:pf")
    await CB.on_callback(ctx, pf)  # «To'liq»: M2 = 30 $, 407
    m2 = _pay_btn(ctx, "qz:py")
    assert m2 != m1

    n = len(be.calls)
    await CB.on_callback(ctx, m1)  # the stale «To'lash» of M1
    assert all(c[1] != "finance/debts/12/pay/" for c in be.calls[n:])
    assert "eskirgan" in texts(ctx)[-1]
    d = await ctx.st()
    assert d["step"] == "qz_pay_confirm" and d["alloc"] == 8  # the current confirm survives

    await CB.on_callback(ctx, m2)
    pays = [c for c in be.calls if c[1] == "finance/debts/12/pay/"]
    assert [c[2] for c in pays] == [{"amount_text": None, "allocation": 8}]
    await CB.on_callback(ctx, m2)  # double tap: draft is gone, nothing more is booked
    assert len([c for c in be.calls if c[1] == "finance/debts/12/pay/"]) == 1


async def test_stale_pf_and_ordinary_debt_nonces_and_bare_buttons(be, make_ctx):
    be.routes[("GET", "finance/debts/12/")] = debt()
    be.routes[("POST", "finance/parse/")] = parse_route
    be.routes[("POST", "finance/debts/12/pay/")] = {
        "debt": debt(remaining="1000000.00"),
        "operation": fx("dto.operation.1"),
        "balance": "1.00",
    }
    ctx = make_ctx()
    await CB.on_callback(ctx, "qz:p:12")
    old_pf = _pay_btn(ctx, "qz:pf")
    await CB.on_callback(ctx, "qz:p:12")  # the prompt is shown again
    n = len(be.calls)
    await CB.on_callback(ctx, old_pf)
    assert (await ctx.st())["step"] == "qz_pay_amount" and "eskirgan" in texts(ctx)[-1]
    await MN.on_text(ctx, "500000")
    old_py = _pay_btn(ctx, "qz:py")
    await CB.on_callback(ctx, "qz:p:12")  # restarted: a fresh draft and prompt
    await CB.on_callback(ctx, old_py)
    assert not any(c[1].endswith("/pay/") for c in be.calls[n:])
    await MN.on_text(ctx, "600000")
    await CB.on_callback(ctx, _pay_btn(ctx, "qz:py"))
    assert be.calls[-1][2] == {"amount_text": "600000"}

    # a bare button of an old message must not confirm a newer draft that has a nonce
    ctx = make_ctx()
    await CB.on_callback(ctx, "qz:p:12")
    await MN.on_text(ctx, "500000")
    n = len(be.calls)
    await CB.on_callback(ctx, "qz:py")
    assert not any(c[1].endswith("/pay/") for c in be.calls[n:])
    assert (await ctx.st())["step"] == "qz_pay_confirm" and "eskirgan" in texts(ctx)[-1]

    # bare buttons still work on a draft from before the nonce existed
    ctx = make_ctx()
    await CB.on_callback(ctx, "qz:p:12")
    draft = await ctx.st()
    draft.pop("nz")
    await ctx.set_st(draft)
    await CB.on_callback(ctx, "qz:pf")
    draft = await ctx.st()
    assert draft["step"] == "qz_pay_confirm"
    draft.pop("nz")
    await ctx.set_st(draft)
    await CB.on_callback(ctx, "qz:py")
    assert be.calls[-1][2] == {"amount_text": None} and await ctx.st() is None


async def test_stale_pw_confirm_and_pay_button_data_within_64_bytes(be, make_ctx):
    be.routes[("GET", "finance/debts/12/")] = split_debt()
    ctx = make_ctx()
    await CB.on_callback(ctx, "qz:pw:12")
    whole = _pay_btn(ctx, "qz:py")
    await CB.on_callback(ctx, "qz:po:12:7")  # moves the draft to one order
    n = len(be.calls)
    await CB.on_callback(ctx, whole)
    assert not any(c[1].endswith("/pay/") for c in be.calls[n:])
    assert "eskirgan" in texts(ctx)[-1]
    for kb in (K.debt_pay_amount_kb("1 x", "a" * 8), K.debt_pay_confirm_kb("a" * 8)):
        assert all(len(x.encode()) <= 64 for x in cb_data(kb))
