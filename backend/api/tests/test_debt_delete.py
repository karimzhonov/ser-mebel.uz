"""Debt deletion (owner's rule): staff delete their OWN debt at any age, the admin any
debt, a debt with live payments is never deleted; EDITING keeps the 2-day limit."""

from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from accounting import services as S
from accounting.models import Debt
from api.tests.botkit import load_fixture
from api.tests.test_bot_contract import shape
from core.exceptions import ServiceConflict, ServiceForbidden, ServiceNotFound
from oauth.models import TelegramMember

pytestmark = pytest.mark.django_db

URL = "/api/v1/finance/debts/"
VIEW, ADD = "accounting.view_debt", "accounting.add_debt"
CHANGE, DELETE = "accounting.change_debt", "accounting.delete_debt"
ALL = "accounting.view_all_operations"
BOT = "finance/debts/"
DATA = {
    "creditor": "X",
    "item": "Y",
    "amount_text": "1.5 mln",
    "category": "material",
    "order_ref": "406",
}


def mk(**kw):
    base = dict(
        creditor="Bahor",
        item="LDSP",
        category_code="material",
        order_ref="406",
        amount=1000000,
        actor_admin=True,
    )
    base.update(kw)
    return S.create_debt(**base)


def age(debt, days):
    Debt.objects.filter(pk=debt.pk).update(created_at=timezone.now() - timedelta(days=days))
    return Debt.objects.get(pk=debt.pk)


def link(member, client):
    member.user = client.user
    member.save()


# ------------------------------------------------------------ 1. can_delete_debt
def test_can_delete_debt_rules(site_order, members):
    boss, ali, vali = members
    d = mk(created_by=ali)
    assert S.can_delete_debt(boss, d, True)
    assert S.can_delete_debt(ali, d, False)
    assert not S.can_delete_debt(vali, d, False)
    assert not S.can_delete_debt(None, d, False)
    assert not S.can_delete_debt(ali, None, False)


@pytest.mark.parametrize("days", [3, 30])
def test_owner_deletes_at_any_age(site_order, members, days):
    _, ali, _ = members
    d = age(mk(created_by=ali), days)
    assert S.can_delete_debt(ali, d, False)
    assert not S.can_modify_debt(ali, d, False)  # the edit limit is untouched


def test_null_created_by_is_admin_only(site_order, members):
    boss, ali, _ = members
    d = mk()
    assert d.created_by_id is None
    assert S.can_delete_debt(boss, d, True)
    assert not S.can_delete_debt(ali, d, False)


def test_live_payment_blocks_soft_deleted_payment_does_not(site_order, members):
    boss, ali, _ = members
    d = mk(created_by=ali)
    _, op = S.pay_debt(d, payer=ali, amount=1000)
    assert not S.can_delete_debt(ali, d, False)
    assert not S.can_delete_debt(boss, d, True)
    # annotated row (what the lists use) agrees with the plain row
    assert not S.can_delete_debt(ali, S.debts_qs("all").get(pk=d.pk), False)
    S.delete_operation(op)
    assert S.can_delete_debt(ali, Debt.objects.get(pk=d.pk), False)
    assert S.can_delete_debt(ali, S.debts_qs("all").get(pk=d.pk), False)


def test_deleted_debt_cannot_be_deleted(site_order, members):
    boss, ali, _ = members
    d = mk(created_by=ali)
    S.delete_debt(d)
    assert not S.can_delete_debt(boss, Debt.objects.get(pk=d.pk), True)


# ------------------------------------------------------------ 2. edit limit preserved
def test_old_own_debt_cannot_be_edited_but_can_be_deleted(site_order, members, api):
    _, ali, _ = members
    d = age(mk(created_by=ali), 3)
    c = api(VIEW, CHANGE, DELETE)
    link(ali, c)
    j = c.get(f"{URL}{d.pk}/").json()
    assert j["can_change"] is False and j["can_delete"] is True
    assert c.patch(f"{URL}{d.pk}/", {"item": "z"}, format="json").status_code == 403
    assert Debt.objects.get(pk=d.pk).item == "LDSP"
    assert c.delete(f"{URL}{d.pk}/").status_code == 204
    assert Debt.objects.get(pk=d.pk).is_deleted


# ------------------------------------------------------------ 3. delete_debt_by
def test_delete_debt_by_errors(site_order, members):
    boss, ali, vali = members
    d = mk(created_by=ali)
    with pytest.raises(ServiceForbidden):
        S.delete_debt_by(d, vali, False)
    with pytest.raises(ServiceForbidden):
        S.delete_debt_by(d, None, False)
    assert not Debt.objects.get(pk=d.pk).is_deleted
    S.delete_debt_by(d, ali, False)
    assert Debt.objects.get(pk=d.pk).is_deleted
    with pytest.raises(ServiceNotFound):
        S.delete_debt_by(d, ali, False)
    with pytest.raises(ServiceNotFound):
        S.delete_debt_by(d, boss, True)


def test_delete_debt_by_admin_any_and_null_owner(site_order, members):
    boss, ali, _ = members
    S.delete_debt_by(mk(created_by=ali), boss, True)
    S.delete_debt_by(mk(), boss, True)
    assert Debt.objects.filter(is_deleted=True).count() == 2


def test_delete_debt_by_live_payment_conflict_and_stale_object(site_order, members):
    boss, ali, _ = members
    d = mk(created_by=ali)
    stale = S.debts_qs("all").get(pk=d.pk)  # annotated before any payment
    S.pay_debt(d, payer=ali, amount=1000)
    with pytest.raises(ServiceConflict):
        S.delete_debt_by(stale, ali, False)
    with pytest.raises(ServiceConflict):
        S.delete_debt_by(stale, boss, True)
    assert not Debt.objects.get(pk=d.pk).is_deleted


# ------------------------------------------------------------ 4. bot DELETE
def test_bot_owner_deletes_then_404(site_order, members, bot_client, bot_events):
    _, ali, _ = members
    d = age(mk(created_by=ali), 30)
    r = bot_client.delete(f"{BOT}{d.number}/", actor=200)
    assert r.status_code == 204, r.content
    assert Debt.objects.get(pk=d.pk).is_deleted
    assert bot_client.delete(f"{BOT}{d.number}/", actor=200).status_code == 404
    assert bot_client.delete(f"{BOT}999/", actor=200).status_code == 404
    assert len(bot_events) == 0


def test_bot_staff_cannot_delete_others_admin_can(site_order, members, bot_client, bot_events):
    _, ali, vali = members
    theirs = mk(created_by=vali)
    assert bot_client.delete(f"{BOT}{theirs.number}/", actor=200).status_code == 404
    assert not Debt.objects.get(pk=theirs.pk).is_deleted
    assert bot_client.delete(f"{BOT}{theirs.number}/", actor=100).status_code == 204
    assert Debt.objects.get(pk=theirs.pk).is_deleted
    orphan = mk()
    assert bot_client.delete(f"{BOT}{orphan.number}/", actor=100).status_code == 204
    assert len(bot_events) == 0


def test_bot_delete_with_payment_is_409(site_order, members, bot_client, bot_events):
    boss, ali, _ = members
    d = mk(created_by=ali)
    S.pay_debt(d, payer=ali, amount=1000)
    n = len(bot_events)
    for actor in (200, 100):
        assert bot_client.delete(f"{BOT}{d.number}/", actor=actor).status_code == 409
    assert not Debt.objects.get(pk=d.pk).is_deleted
    assert len(bot_events) == n


def test_bot_delete_refused_for_pending_blocked_task_only(
    site_order, members, bot_client, bot_events
):
    _, ali, _ = members
    d = mk(created_by=ali)
    TelegramMember.objects.create(telegram_id=501, name="P", role="pending")
    TelegramMember.objects.create(telegram_id=502, name="B", role="blocked")
    # task-only (no wallet) owner of a debt written before the wallet was switched off
    off = TelegramMember.objects.create(telegram_id=503, name="NW", role="staff")
    own = mk(created_by=off)
    TelegramMember.objects.filter(pk=off.pk).update(wallet_mode="off")
    for tg, number in ((501, d.number), (502, d.number), (503, own.number)):
        assert bot_client.delete(f"{BOT}{number}/", actor=tg).status_code == 403, tg
    assert not Debt.objects.filter(is_deleted=True).exists()
    assert len(bot_events) == 0


# ------------------------------------------------------------ 5. bot can_delete flag
def test_bot_can_delete_on_get_post_not_in_pay(site_order, members, bot_client):
    _, ali, vali = members
    created = bot_client.post(BOT, actor=200, data=DATA)
    assert created.status_code == 201 and created.json()["can_delete"] is True
    n = created.json()["number"]
    assert bot_client.get(f"{BOT}{n}/", actor=200).json()["can_delete"] is True
    assert bot_client.get(f"{BOT}{n}/", actor=100).json()["can_delete"] is True
    old = age(Debt.objects.get(number=n), 30)
    assert bot_client.get(f"{BOT}{old.number}/", actor=200).json()["can_delete"] is True
    pay = bot_client.post(f"{BOT}{n}/pay/", actor=200, data={"amount_text": "1000"})
    assert pay.status_code == 200
    assert "can_delete" not in pay.json()["debt"]
    assert bot_client.get(f"{BOT}{n}/", actor=200).json()["can_delete"] is False
    assert bot_client.get(f"{BOT}{n}/", actor=100).json()["can_delete"] is False


# ------------------------------------------------------------ 6. site permission and list
def test_site_requires_delete_debt_perm(site_order, members, api):
    _, ali, _ = members
    d = mk(created_by=ali)
    c = api(VIEW, CHANGE)
    link(ali, c)
    assert c.delete(f"{URL}{d.pk}/").status_code == 403
    assert c.get(f"{URL}{d.pk}/").json()["can_delete"] is False
    assert c.get(URL).json()["results"][0]["can_delete"] is False
    assert not Debt.objects.get(pk=d.pk).is_deleted


def test_site_list_can_delete_per_row(site_order, members, api):
    boss, ali, vali = members
    mine = mk(created_by=ali)
    paid = mk(created_by=ali)
    S.pay_debt(paid, payer=ali, amount=1000)
    old = age(mk(created_by=ali), 30)
    c = api(VIEW, DELETE)
    link(ali, c)
    rows = {r["number"]: r["can_delete"] for r in c.get(URL).json()["results"]}
    assert rows == {mine.number: True, paid.number: False, old.number: True}
    # view_all admin: also another's debt and a null-owner debt
    theirs, orphan = mk(created_by=vali), mk()
    adm = api(VIEW, DELETE, ALL)
    rows = {r["number"]: r["can_delete"] for r in adm.get(URL).json()["results"]}
    assert rows[theirs.number] is True and rows[orphan.number] is True
    assert rows[paid.number] is False


def test_site_delete_with_payment_still_400(site_order, members, api):
    _, ali, _ = members
    d = mk(created_by=ali)
    S.pay_debt(d, payer=ali, amount=1000)
    c = api(VIEW, DELETE)
    link(ali, c)
    assert c.delete(f"{URL}{d.pk}/").status_code == 400
    assert not Debt.objects.get(pk=d.pk).is_deleted


def test_site_list_can_delete_adds_no_per_row_queries(site_order, members, api):
    _, ali, _ = members
    c = api(VIEW, DELETE)
    link(ali, c)

    def count():
        with CaptureQueriesContext(connection) as ctx:
            assert c.get(URL).status_code == 200
        return len(ctx)

    mk(created_by=ali)
    one = count()
    for _ in range(4):
        d = mk(created_by=ali)
        S.pay_debt(d, payer=ali, amount=1000)
    assert count() <= one + 1, (one, count())


# ------------------------------------------------------------ 7. after delete
def test_after_delete_debt_is_gone_everywhere(site_order, members, api, bot_client):
    boss, ali, _ = members
    keep = mk(created_by=ali, amount=500)
    gone = age(mk(created_by=ali, amount=1000), 30)
    c = api(VIEW, DELETE, "accounting.view_finance_orders", ALL)
    assert c.get(URL + "stats/").json()["open_count"] == 2
    assert c.delete(f"{URL}{gone.pk}/").status_code == 204
    j = c.get(URL + "?status=all").json()
    assert [x["number"] for x in j["results"]] == [keep.number]
    assert c.get(URL + "stats/").json()["open_count"] == 1
    assert c.get(f"{URL}{gone.pk}/").status_code == 404
    od = c.get("/api/v1/finance/orders/406/").json()["debts"]
    assert [x["number"] for x in od] == [keep.number]
    bj = bot_client.get(BOT, actor=100).json()
    assert [r["number"] for r in bj["rows"]] == [keep.number]
    assert bj["totals"]["open_count"] == 1 and bj["totals"]["open_uzs"] == "500.00"
    # pay refused, number not reused
    assert bot_client.post(f"{BOT}{gone.number}/pay/", actor=200, data={}).status_code == 404
    with pytest.raises(ServiceNotFound):
        S.pay_debt_as(ali, gone.number)
    nxt = mk(created_by=ali)
    assert nxt.number > max(keep.number, gone.number)


# ------------------------------------------------------------ 8. fixture parity
def test_create_response_fixture_parity(site_order, members, bot_client):
    r = bot_client.post(BOT, actor=200, data={**DATA, "amount_text": "6 mln"})
    assert r.status_code == 201, r.content
    assert shape(r.json()) == shape(load_fixture("misc.debt_create_response.json"))
    assert load_fixture("misc.debt_create_response.json")["can_delete"] is True
    assert set(r.json()) == set(load_fixture("dto.debt.1.json")) | {"can_delete"}


# ------------------------------------------------ review round 2: actor state, audit log
@pytest.mark.parametrize(
    "state",
    [
        {"role": "blocked"},
        {"role": "pending"},
        {"wallet_mode": "off"},  # task-only
    ],
)
def test_site_inactive_or_task_only_member_cannot_delete_own_debt(site_order, members, api, state):
    _, ali, _ = members
    d = mk(created_by=ali)
    TelegramMember.objects.filter(pk=ali.pk).update(**state)
    ali.refresh_from_db()
    c = api(VIEW, DELETE)
    link(ali, c)
    assert c.get(f"{URL}{d.pk}/").json()["can_delete"] is False
    assert c.delete(f"{URL}{d.pk}/").status_code == 400
    assert not Debt.objects.get(pk=d.pk).is_deleted


def test_delete_is_logged_with_site_user_and_channel(site_order, members, api, caplog):
    _, ali, _ = members
    d = mk(created_by=ali)
    c = api(VIEW, DELETE)
    link(ali, c)
    with caplog.at_level("WARNING", logger="accounting"):
        assert c.delete(f"{URL}{d.pk}/").status_code == 204
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert f"debt #{d.number} deleted" in msg
    assert f"site_user={c.user.id}" in msg and "channel=site" in msg
