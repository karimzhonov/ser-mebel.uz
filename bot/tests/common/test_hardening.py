import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import quote, unquote

import pytest
from fastapi.testclient import TestClient

import api.routes as routes
from bot.backend import client as cl
from bot.backend.signing import sign
from bot.webhook import webhook_secret
from main import app

http = TestClient(app)


# ---- webhook secret
def test_webhook_secret_shape():
    s = webhook_secret()
    assert len(s) == 48 and all(c in "0123456789abcdef" for c in s)


def test_webhook_rejects_without_secret():
    with patch.object(routes, "feed_update", AsyncMock()) as fu:
        assert http.post("/webhook", json={"update_id": 1}).status_code == 403
        assert (
            http.post(
                "/webhook", json={"update_id": 1}, headers={"X-Telegram-Bot-Api-Secret-Token": "x"}
            ).status_code
            == 403
        )
        fu.assert_not_awaited()
        ok = http.post(
            "/webhook",
            json={"update_id": 1},
            headers={"X-Telegram-Bot-Api-Secret-Token": webhook_secret()},
        )
        assert ok.status_code == 200
        fu.assert_awaited_once()


async def test_set_webhook_passes_secret_and_always_registers():
    from bot import bot, webhook

    info = SimpleNamespace(url=webhook.WEBHOOK_URL, allowed_updates=None)
    with patch.object(bot, "get_webhook_info", AsyncMock(return_value=info)), patch.object(
        bot, "set_webhook", AsyncMock()
    ) as sw:
        await webhook.set_webhook()
    assert sw.await_args.kwargs["secret_token"] == webhook_secret()
    assert {"message", "callback_query", "my_chat_member", "chat_member"} <= set(
        sw.await_args.kwargs["allowed_updates"]
    )


# ---- parse mode
async def test_default_html_and_legacy_plain():
    from bot import bot, send_message

    assert bot.default.parse_mode == "HTML"
    with patch.object(bot, "send_message", AsyncMock()) as sm:
        await send_message(1, "a <b> c", "/x")
    assert sm.await_args.kwargs["parse_mode"] is None


# ---- path signing
def django_full_path(sent_path: str) -> str:
    """What Django's request.get_full_path() gives for the path on the wire: the decoded
    path re-escaped with escape_uri_path's safe set."""
    path, _, qs = sent_path.partition("?")
    out = quote(unquote(path), safe="/:@&+$,-_.!~*'()")
    return out + ("?" + qs if qs else "")


class _Resp:
    status = 200
    headers = {"Content-Type": "application/json"}

    async def read(self):
        return b"{}"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Session:
    def __init__(self):
        self.seen = []

    def request(self, method, url, data=None, headers=None, timeout=None):
        self.seen.append((method, url, headers))
        return _Resp()


@pytest.mark.parametrize(
    "ref", ["406", "SM-003", "Заказ 5", "a@b", "x+y", "100%", "q?x#y", "ёж"]
)
async def test_path_signed_exactly_as_sent(ref):
    c = cl.BackendClient("http://back:8000")
    sess = _Session()
    c._get_session = lambda: sess
    await c.request("GET", f"finance/orders/{ref}/", actor=42, params={"or_temp": 1})
    _, url, headers = sess.seen[0]
    sent = url.raw_path + ("?" + url.raw_query_string if url.raw_query_string else "")
    assert sent == django_full_path(sent)  # server would rebuild the identical string
    assert headers["X-Bot-Signature"] == sign(
        headers["X-Bot-Timestamp"], "GET", sent, "42", b"", nonce=headers["X-Bot-Nonce"]
    )
    # the ref survives a round trip through Django's path decoding
    assert unquote(sent.split("?")[0]).endswith(f"{ref}/")


# ---- /notify per-recipient dedup
async def test_partial_failure_retry_does_not_resend():
    from bot.notify.registry import Notifier

    sent = []
    flaky = {"on": True}

    class B:
        async def send_message(self, chat_id, text, **kw):
            if chat_id == 2 and flaky["on"]:
                raise OSError("boom")
            sent.append(chat_id)
            return SimpleNamespace(message_id=1)

    n1 = Notifier(B(), "evt-1")
    await n1.many([1, 2], "hi")
    assert sent == [1] and [d["ok"] for d in n1.delivered] == [True, False]
    flaky["on"] = False
    n2 = Notifier(B(), "evt-1")
    await n2.many([1, 2], "hi")
    assert sent == [1, 2]  # chat 1 was not sent again
    assert all(d["ok"] for d in n2.delivered)


async def test_ready_card_uses_recipient_as_actor():
    import bot.finance  # noqa: F401
    from bot.finance import notify as fn

    seen = {}

    async def request(method, path, *, actor=None, **kw):
        seen["actor"] = actor
        raise cl.NotFound("x")

    with patch.object(fn.backend, "request", request):
        assert await fn._card_png({"order_ref": "389"}, 777) is None
    assert seen["actor"] == 777


async def test_group_handler_reraises_backend_down_quietly():
    from bot.hr import api as hrapi

    @hrapi.guarded_quiet
    async def h(message):
        raise cl.BackendDown("x")

    @hrapi.guarded_quiet
    async def h2(message):
        raise cl.ServiceRefusal("no")

    with pytest.raises(cl.BackendDown):
        await h(SimpleNamespace())
    assert await h2(SimpleNamespace()) is None


_ = (asyncio, json, time)


async def test_dedup_hit_is_success_with_message_id():
    from bot.notify.registry import Notifier

    class B:
        calls = 0

        async def send_message(self, chat_id, text, **kw):
            B.calls += 1
            return SimpleNamespace(message_id=77)

    await Notifier(B(), "e2").send(5, "x")
    n = Notifier(B(), "e2")
    m = await n.send(5, "x")
    assert B.calls == 1 and m.message_id == 77
    assert n.delivered[0]["ok"] and n.delivered[0]["message_id"] == 77


async def test_member_approved_drops_whoami(fake_redis):
    import bot.finance  # noqa: F401
    from bot.notify.registry import dispatch
    from tests.finance.conftest import fx

    env = fx("event.finance.member_approved")
    tg = env["data"]["member"]["telegram_id"]
    await fake_redis.set(f"whoami:{tg}", "{}")

    class B:
        async def send_message(self, chat_id, text, **kw):
            return SimpleNamespace(message_id=1)

    await dispatch(env, B())
    assert await fake_redis.get(f"whoami:{tg}") is None


async def test_one_crashing_recipient_does_not_stop_the_others():
    from bot.notify.registry import Notifier

    sent = []

    class B:
        async def send_message(self, chat_id, text, **kw):
            if chat_id == 2:
                raise RuntimeError("unexpected")  # not a Telegram / network error
            sent.append(chat_id)
            return SimpleNamespace(message_id=1)

    n = Notifier(B(), "evt-crash")
    await n.many([1, 2, 3], "hi")
    assert sent == [1, 3]
    assert [d["ok"] for d in n.delivered] == [True, False, True]


async def test_hr_send_never_raises():
    from bot.hr import api as hrapi

    class B:
        async def send_message(self, *a, **kw):
            raise RuntimeError("unexpected")

    with patch.object(hrapi, "get_bot", lambda: B()):
        d = await hrapi.send(5, "x")
    assert d["ok"] is False
