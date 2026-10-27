"""Finance bot test kit: a fake Telegram (records every Bot API call) and helpers
that build Telegram updates the way bot/ forwards them."""

import itertools
from datetime import date, timedelta

import pytest
from djmoney.money import Money


class FakeTelegram:
    def __init__(self):
        self.calls = []
        self._ids = itertools.count(1000)

    def __call__(self, method, payload=None, files=None, timeout=30):
        payload = dict(payload or {})
        self.calls.append((method, payload, bool(files)))
        if method == "getFile":
            return {"ok": True, "result": {"file_path": "photos/x.jpg"}}
        chat = payload.get("chat_id")
        return {"ok": True, "result": {"message_id": next(self._ids), "chat": {"id": chat}}}

    def texts(self, chat=None, method=None):
        out = []
        for m, p, _ in self.calls:
            if method and m != method:
                continue
            if chat is not None and str(p.get("chat_id")) != str(chat):
                continue
            out.append(p.get("text") or p.get("caption") or "")
        return out

    def last(self, chat=None):
        t = self.texts(chat)
        return t[-1] if t else ""

    def buttons(self, chat=None):
        """callback_data of the last inline keyboard sent to chat."""
        for m, p, _ in reversed(self.calls):
            if chat is not None and str(p.get("chat_id")) != str(chat):
                continue
            kb = p.get("reply_markup") or {}
            if "inline_keyboard" in kb:
                return [b.get("callback_data") for row in kb["inline_keyboard"] for b in row]
        return []

    def reset(self):
        self.calls.clear()


@pytest.fixture
def tg(monkeypatch, settings):
    settings.TELEGRAM_BOT_TOKEN = "123:TEST"
    fake = FakeTelegram()
    monkeypatch.setattr("accounting.telegram.api.call", fake)
    monkeypatch.setattr(
        "accounting.telegram.api.download_file", lambda fid: (b"\x89PNG fake", "image/png")
    )
    # no QuickChart / CBU in tests
    monkeypatch.setattr("accounting.images._chart", lambda *a, **k: b"png")
    # webhook updates are handled in a worker thread in prod; inline in tests
    monkeypatch.setattr(
        "accounting.telegram.router._executor.submit", lambda fn, *a, **k: fn(*a, **k)
    )
    monkeypatch.setattr("accounting.telegram.router.close_old_connections", lambda: None)
    from constance import config

    config.FIN_USD_RATE = 12000.0
    config.FIN_CHANNEL_ID = ""
    return fake


class Bot:
    """Sends updates into the finance router as user `uid`."""

    _upd = itertools.count(1)
    _msg = itertools.count(1)

    def __init__(self, uid, first_name="User", username=""):
        self.uid = uid
        self.frm = {"id": uid, "is_bot": False, "first_name": first_name, "username": username}

    def text(self, text):
        from accounting.telegram.router import handle_update

        return handle_update(
            {
                "update_id": next(self._upd),
                "message": {
                    "message_id": next(self._msg),
                    "from": self.frm,
                    "chat": {"id": self.uid, "type": "private"},
                    "date": 0,
                    "text": text,
                },
            }
        )

    def photo(self, file_id="PHOTO1", caption=""):
        from accounting.telegram.router import handle_update

        return handle_update(
            {
                "update_id": next(self._upd),
                "message": {
                    "message_id": next(self._msg),
                    "from": self.frm,
                    "chat": {"id": self.uid, "type": "private"},
                    "date": 0,
                    "photo": [{"file_id": file_id}],
                    "caption": caption,
                },
            }
        )

    def press(self, data, message_id=999):
        from accounting.telegram.router import handle_update

        return handle_update(
            {
                "update_id": next(self._upd),
                "callback_query": {
                    "id": "cq",
                    "from": self.frm,
                    "data": data,
                    "message": {
                        "message_id": message_id,
                        "chat": {"id": self.uid, "type": "private"},
                    },
                },
            }
        )


@pytest.fixture
def members(db):
    from oauth.models import TelegramMember

    boss = TelegramMember.objects.create(telegram_id=100, name="Rahbar", role="admin")
    ali = TelegramMember.objects.create(telegram_id=200, name="Ali", role="staff")
    vali = TelegramMember.objects.create(
        telegram_id=300, name="Vali", role="staff", is_bonus_receiver=True
    )
    return boss, ali, vali


@pytest.fixture
def site_order(db, db_client, default_factory):
    """Order №406, 1000 USD, 400 USD paid, in production."""
    from order.models import Order

    return Order.objects.create(
        order_number=406,
        client=db_client,
        reception_date=date.today(),
        end_date=date.today() + timedelta(days=20),
        address="Chilonzor",
        factory=default_factory,
        price=Money(1000, "USD"),
        lost_money=Money(400, "USD"),
        status="working",
    )


from api.tests.conftest import api, make_staff  # noqa: E402,F401 — reuse the API client fixtures
