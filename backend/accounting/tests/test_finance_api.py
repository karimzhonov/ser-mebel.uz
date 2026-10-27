import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from accounting import services as S
from accounting.models import Operation
from api.views.finance import bot_signature

pytestmark = pytest.mark.django_db


@pytest.fixture
def boss_api(api, members):
    """A superuser whose account is the boss's Telegram member."""
    client = api(superuser=True)
    boss = members[0]
    boss.user = client.user
    boss.save()
    return client


def test_telegram_update_requires_signature(tg, members):
    c = APIClient()
    body = json.dumps(
        {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "from": {"id": 200},
                "chat": {"id": 200, "type": "private"},
                "text": "/yordam",
            },
        }
    )
    r = c.post("/api/v1/finance/telegram/update/", body, content_type="application/json")
    assert r.status_code == 403
    r = c.post(
        "/api/v1/finance/telegram/update/",
        body,
        content_type="application/json",
        HTTP_X_BOT_SIGNATURE="nope",
    )
    assert r.status_code == 403
    r = c.post(
        "/api/v1/finance/telegram/update/",
        body,
        content_type="application/json",
        HTTP_X_BOT_SIGNATURE=bot_signature(body.encode()),
    )
    assert r.status_code == 200 and r.data == {"handled": True}


def test_site_creates_operation_and_notifies(tg, boss_api, members, site_order):
    ali = members[1]
    r = boss_api.post(
        "/api/v1/finance/operations/",
        {
            "member": ali.id,
            "kind": "expense",
            "category_code": "material",
            "amount": "250000",
            "order_ref": "406",
            "comment": "LDSP",
        },
        format="json",
    )
    assert r.status_code == 201, r.data
    op = Operation.objects.get()
    assert (
        op.source == "site" and op.site_user_id == boss_api.user.id and op.author.telegram_id == 100
    )
    assert op.order_id == site_order.id
    assert any("Hamyoningizga yozildi" in t for t in tg.texts(200))  # the owner is told


def test_site_usd_and_edit_and_delete(tg, boss_api, members):
    ali = members[1]
    r = boss_api.post(
        "/api/v1/finance/operations/",
        {
            "member": ali.id,
            "kind": "income",
            "category_code": "avans",
            "currency": "USD",
            "orig_amount": "100",
            "rate": "12500",
        },
        format="json",
    )
    op_id = r.data["id"]
    assert Decimal(r.data["amount"]) == Decimal("1250000.00")
    r = boss_api.patch(
        f"/api/v1/finance/operations/{op_id}/", {"orig_amount": "200"}, format="json"
    )
    assert Decimal(r.data["amount"]) == Decimal("2500000.00")
    r = boss_api.patch(
        f"/api/v1/finance/operations/{op_id}/", {"category_code": "ovqat"}, format="json"
    )
    assert r.status_code == 400  # expense category on an income
    assert boss_api.delete(f"/api/v1/finance/operations/{op_id}/").status_code == 204
    assert Operation.objects.get(pk=op_id).is_deleted
    assert boss_api.post(f"/api/v1/finance/operations/{op_id}/restore/").status_code == 200


def test_staff_user_sees_only_own_wallet(tg, api, members):
    boss, ali, vali = members
    S.create_operation(member=ali, kind="expense", amount=1000, category_code="ovqat")
    S.create_operation(member=vali, kind="expense", amount=2000, category_code="ovqat")
    c = api("accounting.view_operation", "accounting.add_operation")
    ali.user = c.user
    ali.save()
    r = c.get("/api/v1/finance/operations/")
    assert [x["member"] for x in r.data["results"]] == [ali.id]
    r = c.post(
        "/api/v1/finance/operations/",
        {"member": vali.id, "kind": "expense", "category_code": "ovqat", "amount": 5},
        format="json",
    )
    assert r.status_code == 403
    assert c.get("/api/v1/finance/checks/").status_code == 403
    # not linked to Telegram at all → refused, not "everything"
    other = api("accounting.view_operation")
    assert other.get("/api/v1/finance/operations/").status_code == 403


def test_without_permission_no_access(api, members):
    assert api().get("/api/v1/finance/operations/").status_code == 403


def test_summary_wallets_orders_checks_export(tg, boss_api, members, site_order):
    boss, ali, _ = members
    S.create_operation(
        member=ali,
        author=boss,
        kind="income",
        amount=1_000_000,
        category_code="rahbar",
        actor_admin=True,
    )
    S.create_operation(
        member=ali, kind="expense", amount=300_000, category_code="material", order_ref="406"
    )
    s = boss_api.get("/api/v1/finance/summary/").data
    assert s["expense"] == 300000 and s["income"] == 0 and s["given_to_staff"] == 1000000
    assert len(s["months"]) == 12
    w = boss_api.get("/api/v1/finance/wallets/").data
    assert {r["member"]["name"]: r["balance"] for r in w["results"]}["Ali"] == 700000
    o = boss_api.get("/api/v1/finance/orders/").data["results"]
    row = [x for x in o if x["ref"] == "406"][0]
    assert (
        row["spent"] == 300000
        and row["total"] == 1000
        and row["paid"] == 400
        and row["rest"] == 600
    )
    d = boss_api.get("/api/v1/finance/orders/406/").data
    assert len(d["operations"]) == 1
    assert isinstance(boss_api.get("/api/v1/finance/checks/").data, list)
    x = boss_api.get("/api/v1/finance/export/")
    assert x.status_code == 200 and x.content[:2] == b"PK"


def test_transfer_from_site(tg, boss_api, members):
    _, ali, vali = members
    r = boss_api.post(
        "/api/v1/finance/operations/transfer/",
        {"sender": ali.id, "receiver": vali.id, "amount": "50000"},
        format="json",
    )
    assert r.status_code == 201
    assert S.balance(vali) == 50000 and S.balance(ali) == -50000


def test_members_roles_and_approve(tg, boss_api, members):
    from oauth.models import TelegramMember

    p = TelegramMember.objects.create(telegram_id=999, name="Yangi", role="pending")
    r = boss_api.patch(
        f"/api/v1/finance/members/{p.id}/", {"role": "staff", "is_feedback": True}, format="json"
    )
    assert r.status_code == 200 and r.data["is_task_only"] is True
    assert any("tasdiqladi" in t for t in tg.texts(999))
    assert boss_api.delete(f"/api/v1/finance/members/{members[1].id}/").status_code == 204


def test_settings_roundtrip(tg, boss_api):
    r = boss_api.patch(
        "/api/v1/finance/settings/", {"FIN_WARN_PERCENT": 70, "FIN_CHANNEL_ID": "@x"}, format="json"
    )
    assert (
        r.status_code == 200
        and r.data["FIN_WARN_PERCENT"] == 70
        and r.data["FIN_CHANNEL_ID"] == "@x"
    )
    assert (
        boss_api.patch("/api/v1/finance/settings/", {"SECRET_KEY": "x"}, format="json").status_code
        == 400
    )


def test_request_give_from_site(tg, boss_api, members):
    req = S.create_request(members[1], {"amount": Decimal(300000), "cur": "UZS"}, "LDSP")
    r = boss_api.post(
        f"/api/v1/finance/requests/{req.id}/give/", {"amount": "250000"}, format="json"
    )
    assert r.status_code == 200 and r.data["status"] == "given"
    assert S.balance(members[1]) == 250000
    assert (
        boss_api.post(f"/api/v1/finance/requests/{req.id}/give/", {}, format="json").status_code
        == 400
    )


# ---------------------------------------------------------------- review fixes
@pytest.fixture
def ali_api(api, members):
    c = api(
        "accounting.view_operation",
        "accounting.add_operation",
        "accounting.change_operation",
        "accounting.delete_operation",
    )
    members[1].user = c.user
    members[1].save()
    return c


def test_staff_cannot_touch_boss_money_on_site(tg, ali_api, members):
    boss, ali, _ = members
    given = S.create_operation(
        member=ali,
        author=boss,
        kind="income",
        amount=1_000_000,
        category_code="rahbar",
        actor_admin=True,
    )
    assert (
        ali_api.patch(
            f"/api/v1/finance/operations/{given.id}/", {"amount": "10000000"}, format="json"
        ).status_code
        == 403
    )
    assert ali_api.delete(f"/api/v1/finance/operations/{given.id}/").status_code == 403
    assert ali_api.post(f"/api/v1/finance/operations/{given.id}/restore/").status_code == 403


def test_staff_site_create_rules(tg, ali_api, members):
    ali = members[1]
    url = "/api/v1/finance/operations/"
    base = {"member": ali.id, "amount": "1000"}
    assert (
        ali_api.post(
            url, {**base, "kind": "income", "category_code": "rahbar"}, format="json"
        ).status_code
        == 400
    )
    assert (
        ali_api.post(
            url, {**base, "kind": "expense", "category_code": "uy"}, format="json"
        ).status_code
        == 400
    )
    assert (
        ali_api.post(
            url, {**base, "kind": "expense", "category_code": "otkazma"}, format="json"
        ).status_code
        == 400
    )
    old = str(date.today() - timedelta(days=10))
    assert (
        ali_api.post(
            url, {**base, "kind": "expense", "category_code": "ovqat", "date": old}, format="json"
        ).status_code
        == 400
    )
    r = ali_api.post(url, {**base, "kind": "expense", "category_code": "ovqat"}, format="json")
    assert r.status_code == 201
    # own recent entry: may edit and delete
    assert (
        ali_api.patch(f"{url}{r.data['id']}/", {"amount": "1500"}, format="json").status_code == 200
    )
    assert ali_api.delete(f"{url}{r.data['id']}/").status_code == 204


def test_bonus_close_refused_while_client_owes(tg, boss_api, site_order):
    from accounting.models import OrderBonus

    bn = OrderBonus.objects.create(
        order_ref="406", total=1000, currency="USD", ready_date=date.today()
    )
    r = boss_api.post(f"/api/v1/finance/bonuses/{bn.id}/close/", {"force": True}, format="json")
    assert r.status_code == 400


def test_settings_ranges(tg, boss_api):
    assert (
        boss_api.patch(
            "/api/v1/finance/settings/", {"FIN_REMINDER_HOUR": 25}, format="json"
        ).status_code
        == 400
    )
    assert (
        boss_api.patch(
            "/api/v1/finance/settings/", {"FIN_BONUS_SINCE": "kecha"}, format="json"
        ).status_code
        == 400
    )


def test_webhook_answers_fast_for_strangers(tg, db):
    c = APIClient()
    body = json.dumps(
        {
            "update_id": 77,
            "message": {
                "message_id": 1,
                "from": {"id": 4242},
                "chat": {"id": 4242, "type": "private"},
                "text": "salom",
            },
        }
    )
    r = c.post(
        "/api/v1/finance/telegram/update/",
        body,
        content_type="application/json",
        HTTP_X_BOT_SIGNATURE=bot_signature(body.encode()),
    )
    assert r.data == {"handled": False}


# ---------------------------------------------------------------- review round 2
def test_staff_cannot_edit_collected_money_or_transfers(tg, ali_api, members):
    _, ali, vali = members
    got = S.create_operation(
        member=ali,
        author=ali,
        kind="income",
        amount=5_000_000,
        category_code="qoldiq",
        comment="Pul oldim (mijozdan qoldiq)",
        internal=True,
    )
    out, _ = S.create_transfer(sender=ali, receiver=vali, amount=1000, author=ali)
    url = "/api/v1/finance/operations/"
    assert ali_api.patch(f"{url}{got.id}/", {"amount": "4000000"}, format="json").status_code == 403
    assert ali_api.patch(f"{url}{out.id}/", {"amount": "1"}, format="json").status_code == 403
    assert (
        ali_api.delete(f"{url}{out.id}/").status_code == 204
    )  # deleting own transfer: as in the bot


def test_site_edit_is_announced(tg, boss_api, members):
    ali = members[1]
    op = S.create_operation(
        member=ali, author=ali, kind="expense", amount=1000, category_code="ovqat"
    )
    r = boss_api.patch(f"/api/v1/finance/operations/{op.id}/", {"amount": "2000"}, format="json")
    assert r.status_code == 200
    assert any("Saytda o'zgartirildi" in t for t in tg.texts(200))


def test_transfer_needs_wallets_on_both_sides(tg, boss_api, members):
    from oauth.models import TelegramMember

    blocked = TelegramMember.objects.create(telegram_id=902, name="Blok", role="blocked")
    r = boss_api.post(
        "/api/v1/finance/operations/transfer/",
        {"sender": members[1].id, "receiver": blocked.id, "amount": "1000"},
        format="json",
    )
    assert r.status_code == 400


def test_webhook_stores_update_before_answering_and_replay_finishes_it(tg, members, monkeypatch):
    from accounting.models import ProcessedUpdate
    from accounting.jobs import replay_updates
    from accounting.telegram import router

    queued = []
    monkeypatch.setattr(
        router._executor, "submit", lambda fn, up: queued.append(up)
    )  # «restart»: never ran
    up = {
        "update_id": 5151,
        "message": {
            "message_id": 1,
            "from": {"id": 200, "first_name": "Ali"},
            "chat": {"id": 200, "type": "private"},
            "text": "💳 Hamyonim",
        },
    }
    assert router.dispatch(up) is True
    assert router.dispatch(up) is True  # Telegram retry: not queued twice
    assert len(queued) == 1
    pu = ProcessedUpdate.objects.get(update_id=5151)
    assert pu.done is False and pu.payload["update_id"] == 5151
    ProcessedUpdate.objects.filter(pk=pu.pk).update(created_at=pu.created_at - timedelta(minutes=5))
    tg.reset()
    replay_updates()
    pu.refresh_from_db()
    assert pu.done and pu.attempts == 1
    assert tg.texts(200)  # the user got the answer after all


def test_blocked_member_keeps_site_greeting(tg, db):
    from oauth.models import TelegramMember

    from accounting.telegram.router import claims

    TelegramMember.objects.create(telegram_id=903, name="Eski", role="blocked")
    up = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "from": {"id": 903},
            "chat": {"id": 903, "type": "private"},
            "text": "/start",
        },
    }
    assert claims(up) is False
