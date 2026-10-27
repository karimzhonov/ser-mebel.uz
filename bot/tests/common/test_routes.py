import json
import time
import uuid
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import api.routes as routes
from bot.backend.signing import signed_headers
from bot.notify.registry import UnknownEvent
from main import app

client = TestClient(app)


def post(path, payload, sign=True):
    body = json.dumps(payload).encode()
    headers = signed_headers("POST", path, None, body) if sign else {}
    return client.post(path, content=body, headers=headers)


def env(event="finance.daily_reminder"):
    return {"id": str(uuid.uuid4()), "event": event, "data": {}}


def test_bad_signature_403():
    assert post("/notify", env(), sign=False).status_code == 403
    h = signed_headers("POST", "/notify", None, b"{}")
    h["X-Bot-Timestamp"] = str(int(time.time()) - 400)
    assert client.post("/notify", content=b"{}", headers=h).status_code == 403


def test_dedup_and_unknown():
    e = env()
    with patch.object(routes, "dispatch", AsyncMock(return_value=[{"chat_id": 1, "ok": True}])):
        r1 = post("/notify", e)
        r2 = post("/notify", e)
    assert r1.json()["delivered"] == [{"chat_id": 1, "ok": True}]
    assert r2.json() == {"ok": True, "duplicate": True}
    with patch.object(routes, "dispatch", AsyncMock(side_effect=UnknownEvent("x"))):
        assert post("/notify", env("no.such")).status_code == 400
