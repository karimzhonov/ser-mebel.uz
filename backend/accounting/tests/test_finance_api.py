from datetime import date, timedelta
from decimal import Decimal

import pytest

from accounting import services as S
from accounting.models import Operation

pytestmark = pytest.mark.django_db


@pytest.fixture
def boss_api(api, members):
    """A superuser whose account is the boss's Telegram member."""
    client = api(superuser=True)
    boss = members[0]
    boss.user = client.user
    boss.save()
    return client


def test_site_creates_operation_and_notifies(bot_events, boss_api, members, site_order):
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
    ev = bot_events.one("finance.operation_created")  # the channel and the owner are told
    assert ev["from_site"] is True and ev["notify_owner"] is True and ev["owner_tg"] == 200
    assert ev["operation"]["number"] == op.number and ev["balance"] == "-250000.00"


def test_site_usd_and_edit_and_delete(bot_events, boss_api, members):
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
    gone = bot_events.one("finance.operation_deleted")
    assert gone["by_name"].endswith("(sayt)") and len(gone["operations"]) == 1
    assert boss_api.post(f"/api/v1/finance/operations/{op_id}/restore/").status_code == 200


def test_staff_user_sees_only_own_wallet(bot_events, api, members):
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


def test_summary_wallets_orders_checks_export(bot_events, boss_api, members, site_order):
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


def test_transfer_from_site(bot_events, boss_api, members):
    _, ali, vali = members
    r = boss_api.post(
        "/api/v1/finance/operations/transfer/",
        {"sender": ali.id, "receiver": vali.id, "amount": "50000"},
        format="json",
    )
    assert r.status_code == 201
    assert S.balance(vali) == 50000 and S.balance(ali) == -50000
    ev = bot_events.one("finance.transfer_created")
    assert ev["inc_member"]["telegram_id"] == 300 and ev["inc_balance"] == "50000.00"


def test_members_roles_and_approve(bot_events, boss_api, members):
    from oauth.models import TelegramMember

    p = TelegramMember.objects.create(telegram_id=999, name="Yangi", role="pending")
    r = boss_api.patch(
        f"/api/v1/finance/members/{p.id}/", {"role": "staff", "is_feedback": True}, format="json"
    )
    assert r.status_code == 200 and r.data["is_task_only"] is True
    assert bot_events.one("finance.member_approved")["member"]["telegram_id"] == 999
    assert boss_api.delete(f"/api/v1/finance/members/{members[1].id}/").status_code == 204


def test_settings_roundtrip(bot_events, boss_api):
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


def test_request_give_from_site(bot_events, boss_api, members):
    req = S.create_request(members[1], {"amount": Decimal(300000), "cur": "UZS"}, "LDSP")
    r = boss_api.post(
        f"/api/v1/finance/requests/{req.id}/give/", {"amount": "250000"}, format="json"
    )
    assert r.status_code == 200 and r.data["status"] == "given"
    assert S.balance(members[1]) == 250000
    ev = bot_events.one("finance.request_answered")
    # an answer given on the site is not announced in the channel
    assert ev["from_site"] is True and ev["post_to_channel"] is False and ev["status"] == "given"
    assert ev["by_name"].endswith("(sayt)") and ev["balance"] == "250000.00"
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


def test_staff_cannot_touch_boss_money_on_site(bot_events, ali_api, members):
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


def test_staff_site_create_rules(bot_events, ali_api, members):
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


def test_bonus_close_refused_while_client_owes(bot_events, boss_api, site_order):
    from accounting.models import OrderBonus

    bn = OrderBonus.objects.create(
        order_ref="406", total=1000, currency="USD", ready_date=date.today()
    )
    r = boss_api.post(f"/api/v1/finance/bonuses/{bn.id}/close/", {"force": True}, format="json")
    assert r.status_code == 400


def test_settings_ranges(bot_events, boss_api):
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


# ---------------------------------------------------------------- review round 2
def test_staff_cannot_edit_collected_money_or_transfers(bot_events, ali_api, members):
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


def test_site_edit_is_announced(bot_events, boss_api, members):
    ali = members[1]
    op = S.create_operation(
        member=ali, author=ali, kind="expense", amount=1000, category_code="ovqat"
    )
    r = boss_api.patch(f"/api/v1/finance/operations/{op.id}/", {"amount": "2000"}, format="json")
    assert r.status_code == 200
    ev = bot_events.one("finance.operation_edited")
    assert ev["before"] == {
        "kind_label": "Chiqim",
        "amount": "1000.00",
        "category_name": "Ovqat",
    } or (ev["before"]["amount"] == "1000.00")
    assert ev["operation"]["amount"] == "2000.00" and ev["by_name"].endswith("(sayt)")
    assert ev["pair"] is None


def test_transfer_needs_wallets_on_both_sides(bot_events, boss_api, members):
    from oauth.models import TelegramMember

    blocked = TelegramMember.objects.create(telegram_id=902, name="Blok", role="blocked")
    r = boss_api.post(
        "/api/v1/finance/operations/transfer/",
        {"sender": members[1].id, "receiver": blocked.id, "amount": "1000"},
        format="json",
    )
    assert r.status_code == 400


# ---------------------------------------------------------------- events from the site
def test_site_reject_request_and_close_bonus_and_site_task_emit_events(
    bot_events, boss_api, members, site_order
):
    from accounting.models import OrderBonus, SiteEntryTask

    req = S.create_request(members[1], {"amount": Decimal(1000), "cur": "UZS"}, "x")
    r = boss_api.post(f"/api/v1/finance/requests/{req.id}/reject/", {}, format="json")
    assert r.status_code == 200 and r.data["status"] == "rejected"
    ev = bot_events.one("finance.request_answered")
    assert ev["status"] == "rejected" and ev["from_site"] is True and ev["post_to_channel"] is False
    # bonus closed on the site once the client owes nothing
    site_order.lost_money = site_order.price
    site_order.save()
    bn = OrderBonus.objects.create(
        order_ref="406", total=1000, currency="USD", ready_date=date.today(), client="K"
    )
    assert (
        boss_api.post(f"/api/v1/finance/bonuses/{bn.id}/close/", {}, format="json").status_code
        == 200
    )
    done = bot_events.one("finance.bonus_done")
    assert done["bonus"]["order_ref"] == "406" and done["fallback"] is False  # Vali is the receiver
    task = SiteEntryTask.objects.create(code="sk1", date=date.today(), order_ref="406", client="K")
    assert (
        boss_api.post(f"/api/v1/finance/site-entry/{task.id}/done/", {}, format="json").status_code
        == 200
    )
    assert bot_events.one("finance.site_entry_done")["task"]["code"] == "sk1"


def test_site_receipt_comes_through_the_bot(boss_api, members, monkeypatch):
    op = S.create_operation(
        member=members[1],
        author=members[1],
        kind="expense",
        amount=1000,
        category_code="ovqat",
        receipt_file_id="FILE1",
    )
    asked = []
    monkeypatch.setattr(
        "api.views.finance.fetch_file",
        lambda fid: asked.append(fid) or (b"\xff\xd8 jpeg", "image/jpeg"),
    )
    r = boss_api.get(f"/api/v1/finance/operations/{op.id}/receipt/")
    assert r.status_code == 200 and r.content == b"\xff\xd8 jpeg" and asked == ["FILE1"]
    monkeypatch.setattr("api.views.finance.fetch_file", lambda fid: None)
    assert boss_api.get(f"/api/v1/finance/operations/{op.id}/receipt/").status_code == 404


def test_bot_webhook_route_is_gone(boss_api):
    assert boss_api.post("/api/v1/finance/telegram/update/", {}, format="json").status_code == 404
