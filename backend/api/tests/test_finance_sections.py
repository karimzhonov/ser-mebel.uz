"""Finance inner sections (Qarzlar, Xulosa, Hamyonlar, Готов va bonuslar, ...): each page has a
permission of its own, VIEW_ALL stays a pure row scope, and migration accounting.0023 hands the
new permissions to exactly those who could already open the page.

Several permissions are asserted by hand (not through oauth.access) on purpose: the endpoints
are the contract, the section table only mirrors it."""

import importlib
from datetime import date
from decimal import Decimal

import pytest
from django.apps import apps
from django.contrib.auth.models import Group, Permission
from rest_framework.test import APIClient

from accounting import services as S
from accounting.models import OrderBonus, Worker
from api.tests.accesskit import set_levels
from oauth import access as A
from oauth.models import User

pytestmark = pytest.mark.django_db

ACC = "accounting."
ALL = ACC + "view_all_operations"
HOME = ACC + "view_finance_home"

# the 13 permissions migration 0023 creates (everything it may delete on the way back)
NEW_PERMS = [
    "view_debt",
    "add_debt",
    "change_debt",
    "delete_debt",
    "view_finance_home",
    "view_finance_summary",
    "view_finance_wallets",
    "view_finance_orders",
    "view_worker_card",
    "view_advances",
    "change_advances",
    "view_finance_checks",
    "view_order_bonus_line",
]

PERIOD = {"date_from": "2026-10-01", "date_to": "2026-10-31"}
DEBT_BODY = {
    "creditor": "X",
    "item": "LDSP",
    "category_code": "material",
    "order_ref": "406",
    "amount": "500000",
}


def p(*names):
    return tuple(ACC + n for n in names)


def rows(resp):
    d = resp.json()
    return d["results"] if isinstance(d, dict) and "results" in d else d


@pytest.fixture
def mk(api, members, site_order, bot_events):
    """A staff client with the given permissions; linked to Ali's wallet unless told not to
    (so a 403 is the permission, not the «not linked to a wallet» scope refusal)."""

    def _mk(*perms, linked=True, member=1):
        c = api(*perms)
        if linked:
            m = members[member]
            m.user = c.user
            m.save()
        return c

    return _mk


def as_user(user):
    c = APIClient()
    c.force_authenticate(User.objects.get(pk=user.pk))  # a fresh instance: no permission cache
    return c


def op(member, amount=1000, **kw):
    kw.setdefault("order_ref", "406")
    kw.setdefault("category_code", "material")
    return S.create_operation(member=member, kind="expense", amount=amount, internal=True, **kw)


def debt(**kw):
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


# (name, url, every permission it needs). Company-wide pages list VIEW_ALL as well.
PAGES = [
    ("summary", "/api/v1/finance/summary/", p("view_finance_summary")),
    ("wallets", "/api/v1/finance/wallets/", p("view_finance_wallets")),
    ("worker-card", "/api/v1/finance/worker-card/", p("view_worker_card") + (ALL,)),
    ("orders", "/api/v1/finance/orders/", p("view_finance_orders") + (ALL,)),
    ("order-detail", "/api/v1/finance/orders/406/", p("view_finance_orders") + (ALL,)),
    ("checks", "/api/v1/finance/checks/", p("view_finance_checks") + (ALL,)),
    ("advances", "/api/v1/finance/advances/", p("view_advances") + (ALL,)),
    (
        "export",
        "/api/v1/finance/export/",
        p(
            "view_finance_summary",
            "view_operation",
            "view_finance_checks",
            "view_worker_card",
            "view_finance_wallets",
        )
        + (ALL,),
    ),
    ("operations", "/api/v1/finance/operations/", p("view_operation")),
    ("debts", "/api/v1/finance/debts/", p("view_debt")),
]
PAGE_IDS = [x[0] for x in PAGES]


# ======================================================== 1. matrix: read / write per endpoint
@pytest.mark.parametrize("name,url,needs", PAGES, ids=PAGE_IDS)
def test_get_needs_every_listed_permission(mk, name, url, needs):
    assert mk().get(url, PERIOD).status_code == 403
    ok = mk(*needs).get(url, PERIOD)
    assert ok.status_code == 200, ok.content
    for missing in needs:
        rest = [x for x in needs if x != missing]
        r = mk(*rest).get(url, PERIOD)
        assert r.status_code == 403, f"{name}: still open without {missing}"


@pytest.mark.parametrize("perm", ["view_operation", "view_debt"])
def test_order_options_needs_operation_or_debt_view(mk, perm):
    url = "/api/v1/finance/order-options/"
    assert mk().get(url).status_code == 403
    assert mk(ACC + "view_finance_summary").get(url).status_code == 403
    assert mk(ACC + perm).get(url).status_code == 200


def test_operations_write_matrix(mk):
    url = "/api/v1/finance/operations/"
    view = mk(*p("view_operation"), ALL)
    assert view.post(url, {}, format="json").status_code == 403
    assert view.patch(url + "999999/", {}, format="json").status_code == 403
    assert view.delete(url + "999999/").status_code == 403
    add = mk(*p("view_operation", "add_operation"), ALL)
    assert add.post(url, {}, format="json").status_code == 400  # past the permission check
    chg = mk(*p("view_operation", "change_operation"), ALL)
    assert chg.patch(url + "999999/", {}, format="json").status_code == 404
    assert chg.delete(url + "999999/").status_code == 403
    dele = mk(*p("view_operation", "delete_operation"), ALL)
    assert dele.delete(url + "999999/").status_code == 404


def test_debts_write_matrix(mk, members):
    url = "/api/v1/finance/debts/"
    d = debt()
    view = mk(*p("view_debt"), ALL)
    assert view.post(url, DEBT_BODY, format="json").status_code == 403
    assert view.patch(f"{url}{d.pk}/", {"item": "z"}, format="json").status_code == 403
    assert view.delete(f"{url}{d.pk}/").status_code == 403
    assert view.post(f"{url}{d.pk}/pay/", {"member": 1}, format="json").status_code == 403
    add = mk(*p("view_debt", "add_debt"), ALL)
    assert add.post(url, DEBT_BODY, format="json").status_code in (200, 201)
    assert add.patch(f"{url}{d.pk}/", {"item": "z"}, format="json").status_code == 403
    chg = mk(*p("view_debt", "change_debt"), ALL)
    r = chg.patch(f"{url}{d.pk}/", {"item": "yangi"}, format="json")
    assert r.status_code == 200, r.content
    assert chg.delete(f"{url}{d.pk}/").status_code == 403
    dele = mk(*p("view_debt", "delete_debt"), ALL)
    assert dele.delete(f"{url}{d.pk}/").status_code in (200, 204)


def test_debt_flags_follow_debt_permissions_not_operation_ones(mk):
    d = debt()
    only_op = mk(*p("view_debt", "change_operation", "delete_operation"), ALL)
    r = only_op.get(f"/api/v1/finance/debts/{d.pk}/")
    assert r.status_code == 200
    assert r.json()["can_change"] is False and r.json()["can_delete"] is False
    debts = mk(*p("view_debt", "change_debt", "delete_debt"), ALL)
    r = debts.get(f"/api/v1/finance/debts/{d.pk}/")
    assert r.json()["can_change"] is True and r.json()["can_delete"] is True


def test_advances_write_needs_change_advances_and_view_all(mk):
    url = "/api/v1/finance/advances/"
    body = {"advance": 999999, "action": "accept"}
    # the old rule (view_operation + add_operation + VIEW_ALL) is not enough any more
    old = mk(*p("view_operation", "add_operation", "view_advances"), ALL)
    assert old.post(url, body, format="json").status_code == 403
    no_scope = mk(*p("view_advances", "change_advances"))
    assert no_scope.post(url, body, format="json").status_code == 403
    ok = mk(*p("view_advances", "change_advances"), ALL)
    assert ok.post(url, body, format="json").status_code == 404  # past the gate: no such advance


# ===================================================================== 2. isolation
def test_qarzlar_only_holder_cannot_open_other_pages(mk):
    c = mk(*p("view_debt", "add_debt", "change_debt", "delete_debt"))
    assert c.get("/api/v1/finance/debts/").status_code == 200
    for url in (
        "/api/v1/finance/operations/",
        "/api/v1/finance/summary/",
        "/api/v1/finance/wallets/",
        "/api/v1/finance/export/",
    ):
        assert c.get(url, PERIOD).status_code == 403, url


def test_amallar_only_holder_cannot_open_debts(mk):
    c = mk(*p("view_operation", "add_operation", "change_operation", "delete_operation"))
    assert c.get("/api/v1/finance/operations/").status_code == 200
    assert c.get("/api/v1/finance/debts/").status_code == 403
    assert c.post("/api/v1/finance/debts/", DEBT_BODY, format="json").status_code == 403
    for url in ("summary", "wallets", "worker-card", "checks", "advances"):
        assert c.get(f"/api/v1/finance/{url}/", PERIOD).status_code == 403, url


def test_followup_only_holder_cannot_open_operations(mk):
    c = mk(
        *p("view_orderbonus", "view_warrantyletter", "view_siteentrytask", "view_clientfeedback")
    )
    assert c.get("/api/v1/finance/bonuses/").status_code == 200
    assert c.get("/api/v1/finance/operations/").status_code == 403
    assert c.get("/api/v1/finance/debts/").status_code == 403
    assert c.get("/api/v1/finance/summary/", PERIOD).status_code == 403


# ============================================================== 3. VIEW_ALL is only a scope
@pytest.mark.parametrize("name,url,needs", PAGES, ids=PAGE_IDS)
def test_view_all_alone_opens_no_inner_page(mk, name, url, needs):
    assert mk(ALL).get(url, PERIOD).status_code == 403


def test_view_all_alone_opens_no_inner_write(mk):
    c = mk(ALL)
    assert c.post("/api/v1/finance/operations/", {}, format="json").status_code == 403
    assert c.post("/api/v1/finance/debts/", DEBT_BODY, format="json").status_code == 403
    assert c.post("/api/v1/finance/advances/", {}, format="json").status_code == 403
    assert c.get("/api/v1/finance/order-options/").status_code == 403
    assert c.get("/api/v1/finance/options/").status_code == 403


def test_page_permission_keeps_the_row_scope(mk, members):
    boss, ali, _ = members
    op(boss, 1000)
    op(ali, 2000)
    own = mk(*p("view_operation"))  # linked to Ali
    assert len(rows(own.get("/api/v1/finance/operations/"))) == 1
    everyone = mk(*p("view_operation"), ALL, member=2)
    assert len(rows(everyone.get("/api/v1/finance/operations/"))) == 2


def test_debts_keep_the_row_scope_too(mk, members):
    boss, ali, _ = members
    debt(created_by=boss, creditor="Boss qarzi")
    debt(created_by=ali, creditor="Ali qarzi")
    own = mk(*p("view_debt"))
    assert len(rows(own.get("/api/v1/finance/debts/"))) == 1
    everyone = mk(*p("view_debt"), ALL, member=2)
    assert len(rows(everyone.get("/api/v1/finance/debts/"))) == 2


def test_summary_and_wallets_without_view_all_need_a_linked_wallet(mk):
    for page in ("summary", "wallets"):
        c = mk(ACC + f"view_finance_{page}", linked=False)
        assert c.get(f"/api/v1/finance/{page}/", PERIOD).status_code == 403
        assert (
            mk(ACC + f"view_finance_{page}").get(f"/api/v1/finance/{page}/", PERIOD).status_code
            == 200
        )


# ======================================================== 4. card needs its own permission
def test_orders_permission_does_not_open_the_worker_card(mk):
    c = mk(*p("view_finance_orders"), ALL)
    assert c.get("/api/v1/finance/orders/", PERIOD).status_code == 200
    assert c.get("/api/v1/finance/worker-card/", PERIOD).status_code == 403


def test_company_wide_pages_refuse_without_view_all(mk):
    for perm, url in (
        ("view_worker_card", "worker-card"),
        ("view_finance_orders", "orders"),
        ("view_finance_checks", "checks"),
        ("view_advances", "advances"),
    ):
        assert mk(ACC + perm).get(f"/api/v1/finance/{url}/", PERIOD).status_code == 403, url


# ============================================================== 5. order detail pieces
def test_order_detail_hides_operations_debts_bonus_independently(mk, members):
    _, ali, _ = members
    op(ali, 1000)
    debt()
    OrderBonus.objects.create(order_ref="406", total=1000, currency="USD", ready_date=date.today())
    url = "/api/v1/finance/orders/406/"
    base = p("view_finance_orders") + (ALL,)

    def get(*extra):
        r = mk(*base, *extra).get(url)
        assert r.status_code == 200, r.content
        d = r.json()
        assert {"operations", "debts", "bonus"} <= set(d)  # keys stay, whatever the rights
        return d

    d = get()
    assert d["operations"] == [] and d["debts"] == [] and d["bonus"] is None
    d = get(*p("view_operation"))
    assert len(d["operations"]) == 1 and d["debts"] == [] and d["bonus"] is None
    d = get(*p("view_debt"))
    assert d["operations"] == [] and len(d["debts"]) == 1 and d["bonus"] is None
    d = get(*p("view_order_bonus_line"))
    assert d["operations"] == [] and d["debts"] == [] and d["bonus"] is not None
    # the bonus module's own view does not leak the bonus line into the order page
    d = get(*p("view_orderbonus"))
    assert d["bonus"] is None
    d = get(*p("view_operation", "view_debt", "view_order_bonus_line"))
    assert len(d["operations"]) == 1 and len(d["debts"]) == 1 and d["bonus"] is not None


# ==================================================================== 6. export
def test_export_refuses_when_any_required_permission_is_missing(mk):
    needs = PAGES[PAGE_IDS.index("export")][2]
    for missing in needs:
        c = mk(*[x for x in needs if x != missing])
        assert c.get("/api/v1/finance/export/", PERIOD).status_code == 403, missing
    r = mk(*needs).get("/api/v1/finance/export/", PERIOD)
    assert r.status_code == 200 and r.content[:2] == b"PK"  # an xlsx is a zip


# ================================================== 7. salary_by_worker follows the card right
def _salary(member):
    Worker.objects.create(group="Zavod", name="Dilmurod")
    return op(
        member,
        3_000_000,
        category_code="oylik",
        worker="Dilmurod",
        pay_type="Oylik",
        on_date=date(2026, 10, 20),
        order_ref=None,
    )


def test_salary_by_worker_hidden_for_company_scope_without_card_permission(mk, members):
    _salary(members[1])
    url = "/api/v1/finance/summary/"
    company = mk(*p("view_finance_summary"), ALL)
    assert company.get(url, PERIOD).json()["salary_by_worker"] == []
    with_card = mk(*p("view_finance_summary", "view_worker_card"), ALL, member=2)
    names = [x["name"] for x in with_card.get(url, PERIOD).json()["salary_by_worker"]]
    assert names == ["Dilmurod"]


def test_salary_by_worker_kept_for_a_scoped_users_own_wallet(mk, members):
    _salary(members[1])
    own = mk(*p("view_finance_summary"))  # Ali, no VIEW_ALL
    r = own.get("/api/v1/finance/summary/", PERIOD)
    assert [x["name"] for x in r.json()["salary_by_worker"]] == ["Dilmurod"]


# ================================================================ 8. overview / order flag
def test_overview_accounting_and_wallets_need_view_all_and_finance_home(mk):
    url = "/api/v1/dashboard/overview/"
    for perms, shown in (
        ((ALL,), False),
        ((HOME,), False),
        ((ALL, HOME), True),
    ):
        d = mk("order.view_order", *perms).get(url).json()
        assert (d["accounting"] is not None) is shown, perms
        assert (d["wallets"] is not None) is shown, perms


def test_order_finance_flag_needs_view_all_and_orders_permission(mk, site_order):
    url = f"/api/v1/orders/{site_order.pk}/"

    def flag(*perms):
        r = mk("order.view_order", *perms).get(url)
        assert r.status_code == 200, r.content
        return r.json()["actions"]["finance"]

    assert flag() is False
    assert flag(ALL) is False
    assert flag(ACC + "view_finance_orders") is False
    assert flag(ALL, ACC + "view_finance_orders") is True


# ============================================================ 9. finance/options/
OPTIONS = "/api/v1/finance/options/"
OPTION_PERMS = [
    "view_operation",
    "view_debt",
    "view_finance_summary",
    "view_finance_orders",
    "view_monthreport",
]


@pytest.fixture
def usd(monkeypatch):
    monkeypatch.setattr("accounting.services.usd_rate", lambda: Decimal("12500"))


def test_options_need_a_qualifying_permission(mk, usd):
    assert mk().get(OPTIONS).status_code == 403
    for unrelated in ("view_orderbonus", "view_finance_wallets", "view_advances"):
        assert mk(ACC + unrelated).get(OPTIONS).status_code == 403, unrelated
    for perm in OPTION_PERMS:
        r = mk(ACC + perm).get(OPTIONS)
        assert r.status_code == 200, perm
        assert r.json()["usd_rate"] == 12500.0 and r.json()["categories"]


def test_options_expose_no_private_fields(mk, usd, members):
    Worker.objects.create(
        group="Sinov",
        name="Sinovchi",
        pay_day=5,
        passport_number="AA1234567",
        pinfl="12345678901234",
    )
    c = mk(*p("view_operation", "add_operation"), ALL)
    r = c.get(OPTIONS)
    d = r.json()
    assert d["members"] and d["workers"]
    assert all(set(m) == {"id", "name", "role", "has_wallet"} for m in d["members"])
    assert all(set(w) == {"name", "is_active", "is_boss"} for w in d["workers"])
    assert all(set(x) == {"name", "is_active"} for x in d["cars"])
    text = r.content.decode()
    for secret in ("telegram_id", "pay_day", "passport", "AA1234567", "12345678901234"):
        assert secret not in text, secret


def test_options_members_only_with_view_all(mk, usd):
    assert mk(*p("view_operation")).get(OPTIONS).json()["members"] == []
    assert len(mk(*p("view_operation"), ALL, member=2).get(OPTIONS).json()["members"]) == 3


def test_options_workers_and_cars_only_with_a_write_permission(mk, usd):
    Worker.objects.create(group="Sinov", name="Sinovchi")
    plain = mk(*p("view_operation")).get(OPTIONS).json()
    assert plain["workers"] == [] and plain["cars"] == []
    add = mk(*p("view_operation", "add_operation"), member=2).get(OPTIONS).json()
    assert "Sinovchi" in [w["name"] for w in add["workers"]]
    chg = mk(*p("view_debt", "change_operation"), linked=False).get(OPTIONS).json()
    assert "Sinovchi" in [w["name"] for w in chg["workers"]]
    # add_debt is not an operation write permission
    debts = mk(*p("view_debt", "add_debt"), linked=False).get(OPTIONS).json()
    assert debts["workers"] == [] and debts["cars"] == []


# ====================================================================== 10. paying a debt
def test_pay_with_add_debt_works_without_add_operation(mk, members):
    _, ali, _ = members
    d = debt(created_by=ali)
    c = mk(*p("view_debt", "add_debt"))  # Ali's wallet, no add_operation anywhere
    assert not c.user.has_perm(ACC + "add_operation")
    r = c.post(f"/api/v1/finance/debts/{d.pk}/pay/", {"member": ali.pk}, format="json")
    assert r.status_code == 200, r.content
    assert r.json()["debt"]["status"] == "closed"


def test_pay_with_add_operation_only_is_refused(mk, members):
    _, ali, _ = members
    d = debt(created_by=ali)
    c = mk(*p("view_debt", "add_operation"))
    r = c.post(f"/api/v1/finance/debts/{d.pk}/pay/", {"member": ali.pk}, format="json")
    assert r.status_code == 403


def test_pay_by_an_unlinked_user_is_still_refused(mk, members):
    from accounting.models import Operation

    _, ali, _ = members
    d = debt(created_by=ali)
    before = Operation.objects.count()
    c = mk(*p("view_debt", "add_debt"), linked=False)
    r = c.post(f"/api/v1/finance/debts/{d.pk}/pay/", {"member": ali.pk}, format="json")
    assert r.status_code == 403
    assert Operation.objects.count() == before


# ==================================================================== 11-13. access table
FINANCE_KEYS = [s.key for s in A.SECTIONS if s.key.startswith("finance")]


def test_finance_sections_are_pairwise_disjoint():
    by = {s.key: s for s in A.SECTIONS}
    perms = {k: A._view(by[k]) | A._edit(by[k]) for k in FINANCE_KEYS}
    for i, a in enumerate(FINANCE_KEYS):
        for b in FINANCE_KEYS[i + 1 :]:
            assert not perms[a] & perms[b], (a, b, perms[a] & perms[b])


def test_old_finance_key_is_gone_and_the_new_ones_exist():
    assert "finance" not in {s.key for s in A.SECTIONS}
    assert {
        "finance_all", "finance_home", "finance_summary", "finance_operations", "finance_debts",
        "finance_wallets", "finance_orders", "finance_requests", "finance_reports",
        "finance_worker_card", "finance_advances", "finance_followup", "finance_checks",
        "finance_catalogs", "finance_settings",
    } <= set(FINANCE_KEYS)  # fmt: skip


def _top_levels():
    by = {s.key: s for s in A.SECTIONS}
    return {k: ("edit" if by[k].edit and k not in A._SINGLE else "view") for k in FINANCE_KEYS}


def _levels(report):
    return {s["key"]: s["level"] for s in report["sections"] if s["key"] in FINANCE_KEYS}


@pytest.mark.parametrize("key", FINANCE_KEYS)
def test_section_round_trips_for_a_user_without_touching_the_others(make_staff, key):
    by = {s.key: s for s in A.SECTIONS}
    user = make_staff()
    top = _top_levels()
    assert set_levels(user, top).status_code == 200
    steps = ["none", "view"] + (["edit"] if by[key].edit and key not in A._SINGLE else [])
    for lvl in steps + ["none", top[key]]:
        r = set_levels(user, {key: lvl})
        assert r.status_code == 200, r.data
        got = _levels(A.access(User.objects.get(pk=user.pk)))
        assert got[key] == lvl, (key, lvl, got[key])
        assert {k: v for k, v in got.items() if k != key} == {
            k: v for k, v in top.items() if k != key
        }, (key, lvl)


@pytest.mark.parametrize("key", FINANCE_KEYS)
def test_section_round_trips_for_a_group_without_touching_the_others(key):
    by = {s.key: s for s in A.SECTIONS}
    group = Group.objects.create(name="Sinov lavozim")
    top = _top_levels()
    A.set_group_access(group, top)
    steps = ["none", "view"] + (["edit"] if by[key].edit and key not in A._SINGLE else [])
    for lvl in steps + ["none", top[key]]:
        got = _levels(A.set_group_access(group, {key: lvl}))
        assert got[key] == lvl, (key, lvl, got[key])
        assert {k: v for k, v in got.items() if k != key} == {
            k: v for k, v in top.items() if k != key
        }, (key, lvl)


def test_finance_key_is_refused_with_400(admin_api, make_staff):
    assert set_levels(make_staff(), {"finance": "view"}).status_code == 400
    gid = admin_api.post("/api/v1/groups/", {"name": "Eski kalit"}, format="json").data["id"]
    r = admin_api.post(
        f"/api/v1/groups/{gid}/access/", {"levels": {"finance": "view"}}, format="json"
    )
    assert r.status_code == 400
    assert not Group.objects.get(pk=gid).permissions.exists()


def test_partial_holder_shows_custom_and_keeps_the_rest(make_staff):
    user = make_staff(*p("add_debt", "view_finance_summary"))
    got = _levels(A.access(user))
    assert got["finance_debts"] == "custom"  # add without view: set by hand, kept until changed
    assert got["finance_summary"] == "view"
    assert got["finance_operations"] == "none"
    group = Group.objects.create(name="Qisman")
    group.permissions.add(Permission.objects.get(codename="change_debt"))
    assert _levels(A.group_access(group))["finance_debts"] == "custom"


def test_every_finance_permission_exists_in_the_database():
    have = {
        f"{a}.{c}" for a, c in Permission.objects.values_list("content_type__app_label", "codename")
    }
    by = {s.key: s for s in A.SECTIONS}
    need = set().union(*(A._view(by[k]) | A._edit(by[k]) for k in FINANCE_KEYS))
    assert not need - have, need - have
    assert {ACC + n for n in NEW_PERMS} <= have


# ============================================================ 14-18. migration 0023
def migration():
    return importlib.import_module("accounting.migrations.0023_finance_inner_sections")


def new_perm_qs():
    return Permission.objects.filter(content_type__app_label="accounting", codename__in=NEW_PERMS)


def old(*names):
    return [Permission.objects.get(content_type__app_label="accounting", codename=n) for n in names]


def pre_migration_state():
    """The database as it was before 0023: the new permissions do not exist (their
    group / user rows went with them)."""
    new_perm_qs().delete()
    assert not new_perm_qs().exists()


def holder_user(make_staff, perms, via):
    """The same old permissions held directly by the user or through one group."""
    user = make_staff()
    if via == "user":
        user.user_permissions.add(*old(*perms))
    else:
        g = Group.objects.create(name=f"Lavozim {via} {user.pk}")
        g.permissions.add(*old(*perms))
        g.user_set.add(user)
    return user


# what an old holder of view_operation + view_all_operations could open before (every one of
# these must open again, for the same person, after the migration)
OLD_VIEW_ALL_PAGES = [
    "/api/v1/finance/summary/",
    "/api/v1/finance/wallets/",
    "/api/v1/finance/worker-card/",
    "/api/v1/finance/orders/",
    "/api/v1/finance/orders/406/",
    "/api/v1/finance/checks/",
    "/api/v1/finance/advances/",
    "/api/v1/finance/export/",
    "/api/v1/finance/debts/",
    "/api/v1/finance/operations/",
    "/api/v1/finance/order-options/",
]


def statuses(user, urls):
    c = as_user(user)
    return {u: c.get(u, PERIOD).status_code for u in urls}


@pytest.mark.parametrize("via", ["user", "group"])
def test_migration_keeps_a_view_all_operation_holder_able_to_open_every_page(
    make_staff, site_order, via
):
    user = holder_user(make_staff, ["view_operation", "view_all_operations"], via)
    pre_migration_state()
    before = statuses(user, OLD_VIEW_ALL_PAGES)
    # the pages that run on view_operation itself never closed; every new-permission page did
    open_before = {u for u, c in before.items() if c == 200}
    assert open_before == {
        "/api/v1/finance/operations/",
        "/api/v1/finance/order-options/",
    }, before
    migration().forward(apps, None)
    after = statuses(user, OLD_VIEW_ALL_PAGES)
    assert after == {u: 200 for u in OLD_VIEW_ALL_PAGES}, after


def test_migration_split_holder_gets_the_same_result(make_staff, site_order):
    """view_operation from group A, VIEW_ALL from group B: the check is the union."""
    user = make_staff()
    a = Group.objects.create(name="A: ko'ruvchi")
    a.permissions.add(*old("view_operation"))
    b = Group.objects.create(name="B: hamma hamyon")
    b.permissions.add(*old("view_all_operations"))
    a.user_set.add(user)
    b.user_set.add(user)
    pre_migration_state()
    migration().forward(apps, None)
    after = statuses(user, OLD_VIEW_ALL_PAGES)
    assert after == {u: 200 for u in OLD_VIEW_ALL_PAGES}, after
    assert User.objects.get(pk=user.pk).has_perm(HOME)


def test_migration_mixed_holder_group_and_direct_permissions(make_staff, site_order):
    """A direct user permission and a group's: both are holders and both are copied."""
    user = make_staff()
    user.user_permissions.add(*old("view_operation"))
    g = Group.objects.create(name="Faqat hamyon")
    g.permissions.add(*old("view_all_operations"))
    g.user_set.add(user)
    pre_migration_state()
    migration().forward(apps, None)
    after = statuses(user, OLD_VIEW_ALL_PAGES)
    assert after == {u: 200 for u in OLD_VIEW_ALL_PAGES}, after


@pytest.mark.parametrize("via", ["user", "group"])
def test_migration_maps_every_old_permission_to_its_new_ones(make_staff, via):
    cases = {
        "view_operation": {
            "view_debt", "view_finance_summary", "view_finance_wallets", "view_finance_orders",
            "view_worker_card", "view_advances", "view_finance_checks", "view_order_bonus_line",
        },
        "add_operation": {"add_debt", "change_advances"},
        "change_operation": {"change_debt"},
        "delete_operation": {"delete_debt"},
        "view_all_operations": {"view_finance_home"},
        "view_orderbonus": {"view_order_bonus_line"},
    }  # fmt: skip
    users = {name: holder_user(make_staff, [name], via) for name in cases}
    bystander = make_staff()  # holds nothing
    pre_migration_state()
    migration().forward(apps, None)
    for name, expected in cases.items():
        u = User.objects.get(pk=users[name].pk)
        got = {n for n in NEW_PERMS if u.has_perm(ACC + n)}
        assert got == expected, (name, got ^ expected)
    assert not any(User.objects.get(pk=bystander.pk).has_perm(ACC + n) for n in NEW_PERMS)


def test_migration_view_all_only_holder_keeps_dashboard_and_gains_no_page(make_staff):
    user = holder_user(make_staff, ["view_all_operations"], "group")
    user.user_permissions.add(Permission.objects.get(codename="view_order"))
    pre_migration_state()
    migration().forward(apps, None)
    c = as_user(user)
    d = c.get("/api/v1/dashboard/overview/").json()
    assert d["accounting"] is not None and d["wallets"] is not None
    for url in OLD_VIEW_ALL_PAGES:
        assert c.get(url, PERIOD).status_code == 403, url


def test_migration_view_operation_without_view_all_gains_no_company_page(
    make_staff, members, site_order
):
    user = holder_user(make_staff, ["view_operation"], "user")
    members[1].user = user
    members[1].save()
    pre_migration_state()
    migration().forward(apps, None)
    u = User.objects.get(pk=user.pk)
    assert not u.has_perm(ALL) and not u.has_perm(HOME)
    st = statuses(user, OLD_VIEW_ALL_PAGES)
    for url in (
        "worker-card/", "orders/", "orders/406/", "checks/", "advances/", "export/",
    ):  # fmt: skip
        assert st[f"/api/v1/finance/{url}"] == 403, url
    for url in ("summary/", "wallets/", "debts/", "operations/", "order-options/"):
        assert st[f"/api/v1/finance/{url}"] == 200, url
    assert as_user(user).get("/api/v1/dashboard/overview/").status_code in (200, 403)


def test_migration_forward_twice_changes_nothing(make_staff):
    user = holder_user(
        make_staff, ["view_operation", "add_operation", "view_all_operations"], "user"
    )
    g = holder_user(make_staff, ["view_operation", "change_operation"], "group")
    pre_migration_state()
    m = migration()
    m.forward(apps, None)
    perms = new_perm_qs().count()
    user_rows = User.user_permissions.through.objects.count()
    group_rows = Group.permissions.through.objects.count()
    pairs = set(User.user_permissions.through.objects.values_list("user_id", "permission_id"))
    m.forward(apps, None)
    assert perms == len(NEW_PERMS) == new_perm_qs().count()
    assert User.user_permissions.through.objects.count() == user_rows
    assert Group.permissions.through.objects.count() == group_rows
    assert (
        set(User.user_permissions.through.objects.values_list("user_id", "permission_id")) == pairs
    )
    assert User.objects.get(pk=user.pk).has_perm(ACC + "add_debt")
    assert User.objects.get(pk=g.pk).has_perm(ACC + "change_debt")


def test_migration_forward_creates_missing_permission_rows_with_the_model_names(make_staff):
    pre_migration_state()
    migration().forward(apps, None)
    by = {p_.codename: p_ for p_ in new_perm_qs().select_related("content_type")}
    assert set(by) == set(NEW_PERMS)
    assert by["view_finance_summary"].name == "Moliya: Xulosa"
    assert by["view_debt"].name == "Can view Qarz"
    assert by["view_debt"].content_type.model == "debt"
    assert by["view_finance_home"].content_type.model == "operation"


def test_migration_backward_removes_only_the_new_permissions_and_forward_restores(
    make_staff, site_order
):
    user = holder_user(
        make_staff, ["view_operation", "view_all_operations", "add_operation"], "user"
    )
    g = holder_user(make_staff, ["view_operation"], "group")
    old_perm_ids = set(
        Permission.objects.exclude(pk__in=new_perm_qs()).values_list("pk", flat=True)
    )
    old_user_rows = set(
        User.user_permissions.through.objects.filter(permission_id__in=old_perm_ids).values_list(
            "user_id", "permission_id"
        )
    )
    old_group_rows = set(
        Group.permissions.through.objects.filter(permission_id__in=old_perm_ids).values_list(
            "group_id", "permission_id"
        )
    )
    m = migration()
    m.backward(apps, None)
    assert not new_perm_qs().exists()
    assert set(Permission.objects.values_list("pk", flat=True)) == old_perm_ids
    assert (
        set(User.user_permissions.through.objects.values_list("user_id", "permission_id"))
        == old_user_rows
    )
    assert (
        set(Group.permissions.through.objects.values_list("group_id", "permission_id"))
        == old_group_rows
    )
    # old rights untouched, new pages closed
    assert User.objects.get(pk=user.pk).has_perm(ACC + "view_operation")
    assert statuses(user, ["/api/v1/finance/summary/"]) == {"/api/v1/finance/summary/": 403}
    m.forward(apps, None)
    assert statuses(user, OLD_VIEW_ALL_PAGES) == {u: 200 for u in OLD_VIEW_ALL_PAGES}
    assert User.objects.get(pk=g.pk).has_perm(ACC + "view_finance_summary")


# ============================================================ review round 1 fixes
def test_options_hide_admin_only_categories_without_view_all(mk, usd):
    from accounting.models import FinanceCategory

    FinanceCategory.objects.filter(code="material").update(admin_only=True)
    codes = lambda c: {x["code"] for x in c.get(OPTIONS).json()["categories"]}  # noqa: E731
    assert "material" not in codes(mk(*p("view_operation")))
    assert "material" in codes(mk(*p("view_operation"), ALL, member=2))


def test_month_report_preview_needs_add_monthreport(mk):
    url = "/api/v1/finance/month-reports/preview/"
    assert mk(*p("view_monthreport")).get(url).status_code == 403
    assert mk(*p("view_monthreport", "add_monthreport")).get(url).status_code != 403


def test_summary_and_wallets_embed_no_telegram_id_or_phone(mk):
    for url, get in (
        ("/api/v1/finance/summary/", lambda d: d["member"]),
        ("/api/v1/finance/wallets/", lambda d: d["results"][0]["member"]),
    ):
        r = mk(*p("view_finance_summary", "view_finance_wallets")).get(url, PERIOD)
        assert r.status_code == 200, (url, r.content)
        m = get(r.json())
        assert {"id", "name", "role", "has_wallet"} <= set(m)
        text = r.content.decode()
        assert "telegram_id" not in text and "user_detail" not in text and "phone" not in text


def test_debt_payments_are_trimmed_without_view_operation(mk, members):
    _, ali, _ = members
    d = debt(created_by=ali)
    c = mk(*p("view_debt", "add_debt"))
    r = c.post(f"/api/v1/finance/debts/{d.pk}/pay/", {"member": ali.pk}, format="json")
    assert r.status_code == 200, r.content
    paid = c.get(f"/api/v1/finance/debts/{d.pk}/").json()["payments"][0]
    for row in (r.json()["operation"], paid):
        assert {"number", "date", "amount", "currency", "orig_amount", "member_detail"} <= set(row)
        assert "telegram_id" not in str(row) and "site_user_detail" not in row
        assert "comment" not in row
    full = mk(*p("view_debt", "view_operation"))
    row = full.get(f"/api/v1/finance/debts/{d.pk}/").json()["payments"][0]
    assert "site_user_detail" in row and "comment" in row


def test_debt_with_payments_cannot_be_deleted_for_a_qarzlar_only_user(mk, members):
    _, ali, _ = members
    d = debt(created_by=ali)
    S.pay_debt(d, payer=ali, amount=10)
    c = mk(*p("view_debt", "delete_debt"))
    row = c.get(f"/api/v1/finance/debts/{d.pk}/").json()
    assert row["payments"] and row["can_delete"] is False
    # the server refuses on its own, whatever the flag says
    assert c.delete(f"/api/v1/finance/debts/{d.pk}/").status_code == 400
