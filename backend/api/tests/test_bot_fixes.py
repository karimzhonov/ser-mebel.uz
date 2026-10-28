"""Fix loop 1: path signing, link hardening, replay cache, malformed input, races."""

import json
from datetime import date

import pytest
from django.utils.encoding import escape_uri_path

from accounting import services as S
from accounting.models import SiteEntryTask, WarrantyLetter
from api.tests.botkit import TEST_TOKEN
from core import bot_signing
from core.bot_notify import deterministic_id
from core.exceptions import ServiceConflict, ServiceError
from core.telegram import link_token
from hr import services as HS

pytestmark = pytest.mark.django_db
BOSS, ALI = 100, 200


def test_encoded_path_with_cyrillic_space_and_at_verifies(bot_client, members):
    ref = "Тест ref@x"
    r = bot_client.get(f"finance/orders/{escape_uri_path(ref)}/", actor=ALI)
    assert r.status_code == 404  # signature accepted, no such order
    q = bot_client.get(f"finance/members/?set=staff&x={escape_uri_path('a b')}", actor=BOSS)
    assert q.status_code == 200


def test_manual_order_refs_are_restricted(members):
    for bad in ("Тест", "a b", "x@y", "A" * 21, "a/b"):
        with pytest.raises(ServiceError):
            S.create_manual_order(bad, "K")
    assert S.create_manual_order("SM-007", "K").ref == "SM-007"


def test_plain_digit_link_is_refused_for_everyone(bot_client, make_staff):
    from oauth.models import User

    free = User.objects.create_user(phone="+998900000091", password="x")
    staff = make_staff()
    for u in (free, staff):
        r = bot_client.post("link/", data={"token": str(u.pk), "telegram_id": 701})
        assert r.status_code == 404
        u.refresh_from_db()
        assert u.telegram_id is None
    # a signed token links, and re-links
    r = bot_client.post("link/", data={"token": link_token(free.pk), "telegram_id": 703})
    assert r.status_code == 200
    free.refresh_from_db()
    assert free.telegram_id == 703


def test_manual_order_price_hidden_from_staff(bot_client, members):
    S.create_manual_order("SM-001", "K", "", 5000)
    staff = bot_client.get("finance/orders/SM-001/", actor=ALI).data
    assert staff["manual"] == {"is_closed": False}
    assert bot_client.get("finance/orders/SM-001/", actor=BOSS).data["manual"]["price"] == "5000.00"


def test_sync_sends_use_a_deterministic_envelope_id(group, monkeypatch):
    from core import bot_notify
    from hr import events as E

    seen = []
    monkeypatch.setattr(
        bot_notify, "post_envelope", lambda env, timeout=15: seen.append(env["id"]) or {"ok": True}
    )
    e, _ = HS.upsert_emp({"id": 500, "first_name": "J"}, group)
    day = date(2026, 10, 26)
    E.ask_eta(e, 540, day, repeat=False)
    E.ask_eta(e, 540, day, repeat=False)
    E.ask_eta(e, 540, day, repeat=True)
    assert seen[0] == seen[1] != seen[2]
    assert seen[0] == deterministic_id("hr", "2026-10-26", "ask", 500)


def test_replayed_signature_is_refused(bot_client, members, fake_replay_cache):
    body = b""
    path = "/api/v1/bot/finance/config/"
    h = bot_client.headers("GET", path, ALI, body, ts=None)
    assert bot_client.http.generic("GET", path, **h).status_code == 200
    assert bot_client.http.generic("GET", path, **h).status_code == 200  # reads may repeat
    url = "/api/v1/bot/whoami/"
    payload = json.dumps({"user": {"id": ALI}}).encode()
    h = bot_client.headers("POST", url, ALI, payload, ts=None)
    kw = {"data": payload, "content_type": "application/json", **h}
    assert bot_client.http.generic("POST", url, **kw).status_code == 200
    assert bot_client.http.generic("POST", url, **kw).status_code == 403


def test_replay_cache_down_fails_closed(bot_client, members, monkeypatch):
    def boom():
        raise OSError("redis down")

    monkeypatch.setattr("api.authentication._redis", boom)
    assert bot_client.get("finance/config/", actor=ALI).status_code == 200  # reads skip it
    r = bot_client.post("whoami/", actor=ALI, data={"user": {"id": ALI}})
    assert r.status_code == 403


def test_malformed_input_is_a_400(bot_client, members):
    assert bot_client.post("whoami/", actor=ALI, data={"user": {"id": "abc"}}).status_code == 400
    ok = {"kind": "expense", "category": "ovqat"}
    for amount in ("NaN", "Infinity", "-Infinity", "abc"):
        r = bot_client.post("finance/operations/", actor=ALI, data={**ok, "amount": amount})
        assert r.status_code == 400, amount
    from hr.models import WorkGroup

    HS.upsert_emp({"id": 500, "first_name": "J"}, WorkGroup.objects.create(chat_id=-1, title="Z"))
    r = bot_client.patch("hr/employees/1/", actor=BOSS, data={"toggle_off_day": "x"})
    assert r.status_code == 400
    req = bot_client.post("finance/requests/", actor=ALI, data={"amount_text": "1000"}).data
    r = bot_client.post(
        f"finance/requests/{req['number']}/admin-messages/",
        actor=ALI,
        data={"messages": [["x", "y"]]},
    )
    assert r.status_code == 400
    r = bot_client.post(
        f"finance/requests/{req['number']}/admin-messages/", actor=ALI, data={"messages": 5}
    )
    assert r.status_code == 400


def test_usd_amount_is_recomputed_server_side(bot_client, members):
    r = bot_client.post(
        "finance/operations/",
        actor=ALI,
        data={
            "kind": "expense",
            "category": "ovqat",
            "currency": "USD",
            "amount": "1",
            "orig_amount": "100",
            "rate": "12000",
        },
    )
    assert r.status_code == 201 and r.data["operation"]["amount"] == "1200000.00"


def test_already_done_answers_are_conflicts(group):
    from hr.models import Attendance

    HS.decide_holiday(date(2027, 1, 1), 1)
    with pytest.raises(ServiceConflict):
        HS.decide_holiday(date(2027, 1, 1), 2)
    task = SiteEntryTask.objects.create(code="a", date=date(2026, 10, 26), order_ref="1")
    S.site_entry_done(task, "x")
    with pytest.raises(ServiceConflict):
        S.site_entry_done(task, "y")
    S.create_manual_order("SM-009", "K")
    S.warranty_give("SM-009", "x")
    with pytest.raises(ServiceConflict):
        S.warranty_give("SM-009", "y")
    e, _ = HS.upsert_emp({"id": 500, "first_name": "J"}, group)
    with pytest.raises(ServiceConflict):  # nobody asked for a day off
        HS.answer_off_request(e, date(2026, 10, 26), True)
    HS.set_att(date(2026, 10, 26), e, off_requested=True)
    HS.answer_off_request(e, date(2026, 10, 26), False)
    with pytest.raises(ServiceConflict):
        HS.answer_off_request(e, date(2026, 10, 26), False)
    assert Attendance.objects.get().off_requested is False


def test_warranty_list_is_capped_newest_first(bot_client, members):
    for i in range(60):
        WarrantyLetter.objects.create(order_ref=f"W{i}")
    rows = bot_client.get("finance/warranty/?given=0", actor=300).data
    assert len(rows) == 50 and rows[0]["order_ref"] == "W59"


def test_hr_site_url_uses_admin_base_url(settings):
    from hr.events import site_url

    settings.ADMIN_BASE_URL = "https://x.example/"
    assert site_url() == "https://x.example/hr"


def test_sign_helper_roundtrip_with_encoded_path():
    path = "/api/v1/bot/finance/orders/" + escape_uri_path("Тест x@y") + "/"
    sig = bot_signing.sign(5, "GET", path, 1, b"", token=TEST_TOKEN)
    assert bot_signing.verify(sig, 5, "GET", path, 1, b"", token=TEST_TOKEN, now=5)
    assert json.dumps(path)


def test_nonce_rules(bot_client, members):
    url = "/api/v1/bot/whoami/"
    payload = json.dumps({"user": {"id": ALI}}).encode()

    def hdr(nonce):
        return bot_client.headers("POST", url, ALI, payload, nonce=nonce)

    kw = {"data": payload, "content_type": "application/json"}
    n = "ab" * 16
    h = hdr(n)
    assert bot_client.http.generic("POST", url, **kw, **h).status_code == 200
    assert bot_client.http.generic("POST", url, **kw, **h).status_code == 403  # same nonce
    # same body and second, fresh nonce: fine now
    assert bot_client.http.generic("POST", url, **kw, **hdr("cd" * 16)).status_code == 200
    # missing / malformed nonce on an unsafe method
    h = hdr("")
    assert bot_client.http.generic("POST", url, **kw, **h).status_code == 403
    assert bot_client.http.generic("POST", url, **kw, **hdr("zz" * 16)).status_code == 403
    # a nonce that was not the one signed
    h = hdr("ef" * 16)
    h["HTTP_X_BOT_NONCE"] = "01" * 16
    assert bot_client.http.generic("POST", url, **kw, **h).status_code == 403


def test_usd_rate_is_the_servers(bot_client, members):
    r = bot_client.post(
        "finance/operations/",
        actor=ALI,
        data={
            "kind": "expense",
            "category": "ovqat",
            "currency": "USD",
            "orig_amount": "100",
            "rate": "1",
            "amount": "1",
        },
    )
    assert r.status_code == 201
    assert (
        r.data["operation"]["rate"] == "12000.0000"
        and r.data["operation"]["amount"] == "1200000.00"
    )