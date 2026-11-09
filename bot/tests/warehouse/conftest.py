import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import (
    GetFile,
    SendMediaGroup,
    SendPhoto,
)
from aiogram.types import Chat, File, Message, PhotoSize, User
from crm.conftest import Backend, Env, FakeSession, buttons, cbs, env  # noqa: F401

CONTRACT = Path(__file__).resolve().parents[3] / "docs" / "bot_contract"
UID = 555

PRODUCT = {
    "id": 5,
    "name": "DSP 18mm",
    "code": "DSP18",
    "category": "Plita",
    "unit": "dona",
    "unit_label": "dona",
    "quantity": "10.000",
    "min_quantity": "2.000",
    "avg_cost": "100000.00",
    "value": "1000000.00",
    "low": False,
    "is_active": True,
    "photos_count": 0,
    "cover": None,
    "url": "https://ser-mebel.uz/warehouse?search=DSP18",
    "photos": [],
}


def fx(name):
    name = name if name.endswith(".json") else name + ".json"
    return json.loads((CONTRACT / name).read_text())


def photo(pid, pos=0, tg=""):
    return {
        "id": pid,
        "position": pos,
        "is_cover": pos == 0,
        "width": 800,
        "height": 600,
        "tg_file_id": tg,
    }


def with_photos(*photos, **over):
    p = {**PRODUCT, **over}
    p["photos"] = list(photos)
    p["photos_count"] = len(photos)
    p["cover"] = photos[0] if photos else None
    return p


def _msg(chat_id, mid, **extra):
    return Message(
        message_id=mid,
        date=0,
        chat=Chat(id=chat_id, type="private"),
        from_user=User(id=1, is_bot=True, first_name="bot"),
        **extra,
    )


def _ps(fid):
    return PhotoSize(file_id=fid, file_unique_id=fid + "u", width=10, height=10)


class WhSession(FakeSession):
    """FakeSession that also answers photo sends, albums and file downloads."""

    def __init__(self):
        super().__init__()
        self.bad_ids = set()  # file_ids Telegram refuses (stale cache)
        self._n = 0

    async def stream_content(self, *a, **kw):
        yield b"TGBYTES"

    def _fail(self, media):
        if isinstance(media, str) and media in self.bad_ids:
            raise TelegramBadRequest(method=None, message="Bad Request: wrong file identifier")

    async def make_request(self, bot, method, timeout=None):
        self._n += 1
        if isinstance(method, SendPhoto):
            self.calls.append(method)
            self._fail(method.photo)
            return _msg(method.chat_id, 800 + self._n, photo=[_ps(f"new{self._n}")])
        if isinstance(method, SendMediaGroup):
            self.calls.append(method)
            for m in method.media:
                self._fail(m.media)
            return [
                _msg(method.chat_id, 800 + self._n * 10 + i, photo=[_ps(f"grp{i}")])
                for i, _ in enumerate(method.media)
            ]
        if isinstance(method, GetFile):
            self.calls.append(method)
            return File(file_id=method.file_id, file_unique_id="u", file_path="p/x.jpg")
        return await super().make_request(bot, method, timeout)

    def photos(self):
        return self.of(SendPhoto)

    def groups(self):
        return self.of(SendMediaGroup)


class Files:
    def __init__(self):
        self.uploads = []


@pytest.fixture
def wh(env, monkeypatch):  # noqa: F811
    """env + keeper + a session that supports photos; backend files recorded."""
    from bot.backend.client import backend as real

    s = WhSession()
    env.bot.session = s
    env.session = s
    env.backend.who = {
        "finance_member": None,
        "hr": {"employee": None, "is_admin": False},
        "crm": {},
        "warehouse": {"is_keeper": True},
    }
    env.uploads = []
    env.raw = {}
    orig = env.backend.request

    async def request(method, path, *, actor=None, json=None, params=None, files=None, raw=False):
        if files is not None:
            env.uploads.append((path, json, files))
        m = re.fullmatch(r"warehouse/photos/(\d+)/file/", path)
        if raw and m:
            env.backend.calls.append((method, path, json, params))
            return SimpleNamespace(content=env.raw.get(int(m.group(1)), b"BACKENDJPEG"))
        return await orig(method, path, actor=actor, json=json, params=params, files=files, raw=raw)

    monkeypatch.setattr(real, "request", request)
    return env


def kb_of(msg):
    return cbs(msg.reply_markup)
