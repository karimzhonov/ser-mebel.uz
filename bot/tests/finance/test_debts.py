"""«📕 Qarzlar»: list, add flow, pay flow, notify renderer (mocked backend, fakeredis)."""

from bot.backend.client import Conflict, ServiceRefusal
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
    await CB.on_callback(ctx, "qz:pf")
    assert (await ctx.st())["step"] == "qz_pay_confirm"
    await CB.on_callback(ctx, "qz:py")
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
    await CB.on_callback(ctx, "qz:py")
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
    for arg in ("s", "py", "pf", "k:material", "o:406", "ot"):
        await CB.on_callback(ctx, f"qz:{arg}")
    assert be.calls == [] and texts(ctx) == []
    await ctx.set_st({"t": "qz", "step": "qz_from"})
    await ctx.load()
    for arg in ("s", "py", "pf", "k:material", "o:406", "ot"):
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
