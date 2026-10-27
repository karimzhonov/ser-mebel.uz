from bot.backend.client import BackendDown, Conflict, ServiceRefusal
from bot.finance import keyboards as K
from bot.finance import texts as T
from bot.finance.ctx import run
from bot.finance.handlers import callbacks as CB
from bot.finance.handlers import menu as MN
from bot.finance.handlers import requests as RQ
from bot.finance.handlers import tx as TX

from .conftest import fx, texts


def routes_for_tx(be, cats):
    be.routes[("GET", "finance/config/")] = {"usd_rate": "12000.0000"}
    be.routes[("GET", "finance/categories/")] = cats
    be.routes[("GET", "finance/orders/")] = [fx("dto.order_brief.1")]
    be.routes[("GET", "finance/orders/406/")] = {"ref": "406", "client": "Nazira"}
    be.routes[("GET", "finance/workers/")] = [fx("dto.worker.1")]


async def test_chiqim_flow_posts_contract_payload(be, cats, make_ctx):
    routes_for_tx(be, cats)
    be.routes[("POST", "finance/parse/")] = {
        "amount": "250000.00",
        "cur": "UZS",
        "orig": None,
        "rate": None,
    }
    op = fx("dto.operation.1")
    be.routes[("POST", "finance/operations/")] = {"operation": op, "balance": "100.00"}
    ctx = make_ctx()
    await TX.start_tx(ctx, "expense", ctx.member)
    assert (await ctx.st())["step"] == "amount"
    await MN.on_text(ctx, "250000")
    assert (await ctx.st())["step"] == "category"
    await CB.on_callback(ctx, "cat:material")
    assert (await ctx.st())["step"] == "order"
    await CB.on_callback(ctx, "ord:406")
    assert (await ctx.st())["step"] == "comment"
    await MN.on_text(ctx, "LDSP")
    assert (await ctx.st())["step"] == "confirm"
    await CB.on_callback(ctx, "save")
    assert await ctx.st() is None  # draft cleared before the write
    method, path, body, _ = next(c for c in be.calls if c[1] == "finance/operations/")
    assert method == "POST"
    assert body == {
        "member_tg": ctx.tg_id,
        "kind": "expense",
        "amount": "250000",
        "category": "material",
        "currency": "UZS",
        "orig_amount": None,
        "rate": None,
        "order_ref": "406",
        "comment": "LDSP",
        "receipt_file_id": "",
        "worker": "",
        "pay_type": "",
    }
    assert "Saqlandi" in texts(ctx)[-1]


async def test_usd_without_rate_asks_rate(be, cats, make_ctx):
    routes_for_tx(be, cats)
    be.routes[("GET", "finance/config/")] = {"usd_rate": "0.0000"}

    def parse(j, p):
        if "$" in j["text"]:
            raise ServiceRefusal("kurs yo'q")
        return {"amount": "100.00", "cur": "UZS", "orig": None, "rate": None}

    be.routes[("POST", "finance/parse/")] = parse
    ctx = make_ctx()
    await TX.start_tx(ctx, "expense", ctx.member)
    await MN.on_text(ctx, "100$")
    assert (await ctx.st())["step"] == "rate"
    await MN.on_text(ctx, "12050")
    d = await ctx.st()
    assert d["amount"] == str(100 * 12050) and d["step"] == "category"


async def test_cancel_deletes_tracked(be, make_ctx):
    ctx = make_ctx()
    await ctx.set_st({"step": "amount"})
    await ctx.state.update_data(_flow=[11, 12])
    await ctx.load()
    ctx.cb_msg = 13
    await CB.cancel_flow(ctx)
    deleted = [c.args[1] for c in ctx.bot.delete_message.call_args_list]
    assert deleted == [11, 12, 13]
    assert await ctx.st() is None


async def test_error_messages(be, make_ctx):
    ctx = make_ctx()

    async def refuse():
        raise ServiceRefusal("Bu amalni qilib bo'lmaydi")

    await run(ctx, refuse())
    assert texts(ctx)[-1] == "❗ Bu amalni qilib bo'lmaydi"

    async def down():
        raise BackendDown("x")

    await run(ctx, down())
    assert "vaqtincha" in texts(ctx)[-1]

    async def conflict():
        raise Conflict("allaqachon")

    await run(ctx, conflict())
    assert "allaqachon" in texts(ctx)[-1]


async def test_quick_entry_uses_parse(be, cats, make_ctx):
    routes_for_tx(be, cats)
    be.routes[("POST", "finance/parse/")] = {
        "kind": "expense",
        "val": "350000",
        "cur": "UZS",
        "cat": "material",
        "ord": "406",
        "com": "furnitura",
    }
    ctx = make_ctx()
    await MN.on_text(ctx, "350000 furnitura 406")
    d = await ctx.st()
    assert d["step"] == "confirm" and d["amount"] == "350000" and d["ord"] == "406"


async def test_request_flow(be, make_ctx):
    be.routes[("GET", "finance/members/111222333/balance/")] = {"balance": "5.00"}
    be.routes[("POST", "finance/parse/")] = {
        "amount": "500000.00",
        "cur": "UZS",
        "orig": None,
        "rate": None,
    }
    be.routes[("POST", "finance/requests/")] = fx("dto.money_request.1")
    ctx = make_ctx()
    await RQ.req_start(ctx)
    await MN.on_text(ctx, "500000")
    await CB.on_callback(ctx, "skip:reason")
    _, path, body, _ = be.calls[-1]
    assert path == "finance/requests/" and body == {"amount_text": "500000", "reason": ""}
    assert await ctx.st() is None


def test_callback_data_unchanged():
    assert "🕘 Davomat" in [b.text for row in T.KB_ADMIN.keyboard for b in row]
    assert K.handover_kb(5).inline_keyboard[0][0].callback_data == "pqk:5"
    assert K.saved_kb(5, True).inline_keyboard[0][0].callback_data == "rcpt:5"
