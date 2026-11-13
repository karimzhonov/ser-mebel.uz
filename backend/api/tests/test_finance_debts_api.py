"""«Qarzlar» site API: permissions, wallet scoping, events, filters, query count."""

from decimal import Decimal

import pytest

from accounting import services as S
from accounting.models import Debt

pytestmark = pytest.mark.django_db

URL = "/api/v1/finance/debts/"
VIEW, ADD = "accounting.view_operation", "accounting.add_operation"
CHANGE, DELETE = "accounting.change_operation", "accounting.delete_operation"
ALL = "accounting.view_all_operations"
BODY = {
    "creditor": "X",
    "item": "Y",
    "category_code": "material",
    "order_ref": "406",
    "amount": "500000",
}


def link(member, client):
    member.user = client.user
    member.save()


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


def test_view_only_lists_only_own_debts(site_order, members, api):
    _, ali, vali = members
    mk(created_by=ali)
    mine = mk(created_by=vali)
    c = api(VIEW)
    link(vali, c)
    r = c.get(URL)
    assert r.status_code == 200 and r.json()["count"] == 1
    assert [x["number"] for x in r.json()["results"]] == [mine.number]


def test_permission_gates(site_order, members, api):
    d = mk()
    assert api().get(URL).status_code == 403
    assert api().get(f"{URL}{d.pk}/").status_code == 403
    assert api().get(URL + "stats/").status_code == 403
    v = api(VIEW)
    assert v.post(URL, BODY, format="json").status_code == 403
    assert v.post(f"{URL}{d.pk}/pay/", {"member": 1}, format="json").status_code == 403
    assert v.patch(f"{URL}{d.pk}/", {"item": "z"}, format="json").status_code == 403
    assert v.delete(f"{URL}{d.pk}/").status_code == 403


def test_create_returns_dto_without_notification(site_order, members, api, bot_events):
    _, ali, _ = members
    c = api(VIEW, ADD)
    link(ali, c)
    r = c.post(URL, BODY, format="json")
    assert r.status_code == 201, r.content
    j = r.json()
    assert (
        j["number"] == 1 and j["client"] and j["status"] == "open" and j["remaining"] == "500000.00"
    )
    assert not bot_events.of("finance.debt_created")  # owner: no notification
    assert Debt.objects.get().source == "site"


def test_create_validation_errors_400(site_order, members, api, bot_events):
    _, ali, _ = members
    c = api(VIEW, ADD)
    link(ali, c)
    assert c.post(URL, {**BODY, "order_ref": "99999"}, format="json").status_code == 400
    assert c.post(URL, {**BODY, "category_code": "oylik"}, format="json").status_code == 400
    assert c.post(URL, {**BODY, "amount": "0"}, format="json").status_code == 400
    assert not bot_events.of("finance.debt_created")


def test_create_non_admin_without_member_is_403(site_order, members, api):
    c = api(VIEW, ADD)  # not linked to a TelegramMember, no view_all
    assert c.post(URL, BODY, format="json").status_code == 403


def test_pay_wallet_scoping(site_order, members, api, bot_events):
    boss, ali, vali = members
    from oauth.models import TelegramMember

    nowallet = TelegramMember.objects.create(
        telegram_id=400, name="NoW", role="staff", wallet_mode="off"
    )
    d = mk(created_by=ali)
    c = api(VIEW, ADD)
    link(ali, c)
    r = c.post(f"{URL}{d.pk}/pay/", {"member": vali.pk, "amount": "1000"}, format="json")
    assert r.status_code == 403
    assert not bot_events.of("finance.operation_created")
    # an admin (view_all) may pay from another wallet, but not from a wallet-less one
    a = api(VIEW, ADD, ALL)
    bad = a.post(f"{URL}{d.pk}/pay/", {"member": nowallet.pk, "amount": "1000"}, format="json")
    assert bad.status_code == 400
    ok = a.post(f"{URL}{d.pk}/pay/", {"member": vali.pk, "amount": "1000"}, format="json")
    assert ok.status_code == 200, ok.content
    assert ok.json()["operation"]["debt_number"] == d.number
    assert S.balance(vali) == Decimal("-1000")
    assert bot_events.one("finance.operation_created")


def test_pay_own_wallet_closes_and_conflicts_after(site_order, members, api, bot_events):
    _, ali, _ = members
    d = mk(created_by=ali)
    c = api(VIEW, ADD)
    link(ali, c)
    r = c.post(f"{URL}{d.pk}/pay/", {"member": ali.pk}, format="json")
    assert r.status_code == 200, r.content
    assert (
        r.json()["debt"]["status"] == "closed" and r.json()["operation"]["debt_number"] == d.number
    )
    assert len(bot_events.of("finance.operation_created")) == 1
    again = c.post(f"{URL}{d.pk}/pay/", {"member": ali.pk}, format="json")
    assert again.status_code == 400  # site API folds conflicts into 400
    over = mk(created_by=ali)
    assert (
        c.post(
            f"{URL}{over.pk}/pay/", {"member": ali.pk, "amount": "9999999"}, format="json"
        ).status_code
        == 400
    )


def test_status_search_stats(site_order, members, api):
    _, ali, _ = members
    a = mk(creditor="Alpha", item="Petli", created_by=ali)
    mk(creditor="Beta", item="Kley", currency="USD", amount=None, orig_amount=50, created_by=ali)
    S.pay_debt(a, payer=ali)
    c = api(VIEW)
    link(ali, c)
    assert c.get(URL).json()["count"] == 1  # default open
    assert c.get(URL + "?status=closed").json()["count"] == 1
    assert c.get(URL + "?status=all").json()["count"] == 2
    assert c.get(URL + "?status=all&search=kley").json()["count"] == 1
    assert c.get(URL + "?status=all&search=alpha").json()["results"][0]["creditor"] == "Alpha"
    assert c.get(URL + "?status=all&order_ref=nope").json()["count"] == 0
    st = c.get(URL + "stats/").json()
    assert (
        st["open_count"] == 1
        and Decimal(st["open_usd"]) == Decimal("50")
        and Decimal(st["open_uzs"]) == 0
    )


def test_retrieve_has_payments_and_flags(site_order, members, api):
    _, ali, _ = members
    d = mk(created_by=ali)
    c = api(VIEW, CHANGE, DELETE)
    link(ali, c)
    j = c.get(f"{URL}{d.pk}/").json()
    assert j["payments"] == [] and j["can_delete"] is True and j["can_change"] is True
    S.pay_debt(d, payer=ali, amount=1000)
    j = c.get(f"{URL}{d.pk}/").json()
    assert len(j["payments"]) == 1 and j["payments"][0]["debt_number"] == d.number
    assert j["can_delete"] is False


def test_patch_and_delete_rules(site_order, members, api):
    boss, ali, vali = members
    d = mk(created_by=ali)
    other = api(VIEW, CHANGE, DELETE)
    link(vali, other)
    # another staff member does not even see the debt
    assert other.patch(f"{URL}{d.pk}/", {"item": "z"}, format="json").status_code == 404
    assert other.delete(f"{URL}{d.pk}/").status_code == 404
    # an admin (view_all) may edit anyone's debt
    adm = api(VIEW, CHANGE, DELETE, ALL)
    assert adm.patch(f"{URL}{d.pk}/", {"item": "z2"}, format="json").status_code == 200
    mine = api(VIEW, CHANGE, DELETE)
    link(ali, mine)
    assert mine.patch(f"{URL}{d.pk}/", {"item": "Yangi"}, format="json").json()["item"] == "Yangi"
    assert mine.delete(f"{URL}{d.pk}/").status_code == 204
    assert Debt.objects.get(pk=d.pk).is_deleted
    assert mine.get(f"{URL}{d.pk}/").status_code == 404


def test_delete_refused_with_payments(site_order, members, api):
    _, ali, _ = members
    d = mk()
    S.pay_debt(d, payer=ali, amount=10)
    a = api(VIEW, DELETE, ALL)
    assert a.delete(f"{URL}{d.pk}/").status_code == 400


def test_operations_list_exposes_debt_number(site_order, members, api):
    _, ali, _ = members
    d = mk()
    _, op = S.pay_debt(d, payer=ali, amount=10)
    c = api(VIEW, ALL)
    rows = c.get("/api/v1/finance/operations/").json()
    rows = rows["results"] if isinstance(rows, dict) else rows
    mine = [r for r in rows if r["number"] == op.number]
    assert mine and mine[0]["debt_number"] == d.number


def test_order_detail_includes_debts(site_order, members, api):
    d = mk()
    c = api(VIEW, ALL)
    r = c.get("/api/v1/finance/orders/406/")
    assert r.status_code == 200, r.content
    debts = r.json()["debts"]
    assert [x["number"] for x in debts] == [d.number] and debts[0]["client"]


def test_list_query_count_is_bounded(site_order, members, api, django_assert_max_num_queries):
    _, ali, _ = members
    c = api(VIEW)
    link(ali, c)

    def count():
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as ctx:
            assert c.get(URL).status_code == 200
        return len(ctx)

    for _ in range(2):
        d = mk(created_by=ali)
        S.pay_debt(d, payer=ali, amount=1000)
    base = count()
    for _ in range(8):
        d = mk(created_by=ali)
        S.pay_debt(d, payer=ali, amount=1000)
    assert count() <= base + 1, (base, count())
    with django_assert_max_num_queries(25):
        c.get(URL)


# ---------------------------------------------------------------- owner scoping
def test_staff_does_not_see_or_touch_others_debts(site_order, members, api, bot_events):
    _, ali, vali = members
    mine = mk(created_by=ali)
    theirs = mk(created_by=vali)
    S.pay_debt(theirs, payer=vali, amount=1000)
    c = api(VIEW, ADD, CHANGE, DELETE)
    link(ali, c)
    j = c.get(URL + "?status=all").json()
    assert [x["number"] for x in j["results"]] == [mine.number]
    st = c.get(URL + "stats/").json()
    assert st["open_count"] == 1 and Decimal(st["open_uzs"]) == Decimal("1000000")
    assert c.get(f"{URL}{theirs.pk}/").status_code == 404
    pay = c.post(f"{URL}{theirs.pk}/pay/", {"member": ali.pk, "amount": "10"}, format="json")
    assert pay.status_code == 404
    assert c.patch(f"{URL}{theirs.pk}/", {"item": "z"}, format="json").status_code == 404
    assert c.delete(f"{URL}{theirs.pk}/").status_code == 404
    assert S.balance(ali) == 0 and not Debt.objects.get(pk=theirs.pk).is_deleted
    assert Debt.objects.get(pk=theirs.pk).item == "LDSP"


def test_view_all_user_sees_and_pays_every_debt(site_order, members, api):
    _, ali, vali = members
    a = mk(created_by=ali)
    b = mk(created_by=vali)
    c = api(VIEW, ADD, ALL)
    assert c.get(URL).json()["count"] == 2
    assert c.get(URL + "stats/").json()["open_count"] == 2
    assert c.get(f"{URL}{b.pk}/").status_code == 200
    ok = c.post(f"{URL}{a.pk}/pay/", {"member": ali.pk, "amount": "1000"}, format="json")
    assert ok.status_code == 200, ok.content
    ok = c.post(f"{URL}{b.pk}/pay/", {"member": vali.pk, "amount": "1000"}, format="json")
    assert ok.status_code == 200, ok.content


def test_non_view_all_without_member_is_403_on_debts(site_order, members, api):
    mk()
    c = api(VIEW)
    assert c.get(URL).status_code == 403
    assert c.get(URL + "stats/").status_code == 403
