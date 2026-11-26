"""One debt split across several orders («Qarzlar»).

Owner's rules pinned here: the payer chooses the order on every payment, or «Hammasi»
pays the whole remainder with one Operation per unpaid order; there is no proportional
split; the split is frozen after the first live payment; the staff 2-day edit limit and
the delete rule are unchanged. Money invariants are checked in UZS and USD after every
payment. Everything runs against the real database (only the network is faked)."""

import threading
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.db import connection, connections
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from djmoney.money import Money

from accounting import services as S
from accounting.dto import debt_dto, debt_rows
from accounting.models import Debt, DebtAllocation, ManualOrder, Operation
from api.tests.botkit import load_fixture
from api.tests.test_bot_contract import shape
from core.exceptions import ServiceConflict, ServiceError

pytestmark = pytest.mark.django_db

URL = "/api/v1/finance/debts/"
VIEW, ADD = "accounting.view_debt", "accounting.add_debt"
CHANGE, DELETE = "accounting.change_debt", "accounting.delete_debt"
ALL = "accounting.view_all_operations"
BOT = "finance/debts/"
D = Decimal


# ------------------------------------------------------------------ helpers
@pytest.fixture
def orders(site_order, db_client, default_factory):
    """Site orders 406, 407, 408 (406 is `site_order`)."""
    from order.models import Order

    out = {"406": site_order}
    for n in (407, 408, 409):
        out[str(n)] = Order.objects.create(
            order_number=n,
            client=db_client,
            reception_date=date.today(),
            end_date=date.today() + timedelta(days=20),
            address="Chilonzor",
            factory=default_factory,
            price=Money(1000, "USD"),
            lost_money=Money(400, "USD"),
            status="working",
        )
    return out


@pytest.fixture
def rate():
    S.set_usd_rate(12345.67)
    return D("12345.67")


def som(x):
    """so'm of a USD amount: whole so'm, like services (round(orig * rate))."""
    return D(round(x))


def split_rows(*pairs):
    return [{"ref": r, "amount": a} for r, a in pairs]


def mk_split(pairs=(("406", "20"), ("407", "30"), ("408", "50")), **kw):
    total = sum(D(a) for _, a in pairs)
    base = dict(
        creditor="Furnitura Plus",
        item="Furnitura",
        category_code="material",
        allocations=split_rows(*pairs),
        actor_admin=True,
    )
    if "currency" not in kw:
        base["amount"] = total
    elif kw["currency"] == "USD":
        base["orig_amount"] = total
    base.update(kw)
    return S.create_debt(**base)


def mk_single(**kw):
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


def alloc(debt, ref):
    return DebtAllocation.objects.get(debt=debt, order_ref=ref)


def link(member, client):
    member.user = client.user
    member.save()


def spent(ref):
    return S.order_stats(ref)["spent"]


def snapshot(member, refs):
    return {"bal": S.balance(member), **{r: spent(r) for r in refs}}


class Check:
    """Money invariants, asserted after every payment of one debt."""

    def __init__(self, debt, member, refs=("406", "407", "408", "409")):
        self.debt, self.member, self.refs = debt, member, list(refs)
        self.before = snapshot(member, self.refs)

    def after(self, ops):
        now = snapshot(self.member, self.refs)
        sum_ops = sum((o.amount for o in ops), D(0))
        # the wallet pays exactly the legs; the orders carried the debt since the day it
        # was taken (unpaid part counts in «spent»), so a payment only moves cash — at
        # most a whole so'm of rounding per USD leg
        d_orders = sum((now[r] - self.before[r] for r in self.refs), D(0))
        assert self.before["bal"] - now["bal"] == sum_ops
        assert abs(d_orders) <= len(ops)
        # order_stats == order_stats_bulk for every order
        bulk = S.order_stats_bulk(self.refs)
        for r in self.refs:
            assert bulk.get(r, {"spent": D(0)})["spent"] == S.order_stats(r)["spent"] == now[r]
        # every operation sits on its own share's order; no share is overpaid
        for o in ops:
            assert o.order_ref == o.debt_allocation.order_ref
        paid = S.debt_allocation_paid(Debt.objects.get(pk=self.debt.pk))
        for a in DebtAllocation.objects.filter(debt=self.debt):
            assert paid.get(a.pk, D(0)) <= a.amount
        assert None not in paid
        self.before = now


def pay(debt, ali, **kw):
    return S.pay_debt_legs(debt, payer=ali, actor_admin=True, **kw)


# ------------------------------------------------------------------ 1. money, UZS
def test_uzs_split_chosen_partial_then_rest_then_hammasi(orders, members):
    _, ali, _ = members
    d = mk_split((("406", "200000"), ("407", "300000"), ("408", "500000")))
    assert d.order_ref == "406" and d.total_cur == 1_000_000
    a406, a407, a408 = (alloc(d, r) for r in ("406", "407", "408"))
    chk = Check(d, ali)

    d, ops = pay(d, ali, allocation=a407.pk, amount=D("100000"))
    assert [o.order_ref for o in ops] == ["407"] and ops[0].amount == 100000
    assert ops[0].debt_allocation_id == a407.pk and d.status == "open"
    assert "Qarz #" in ops[0].comment and "(407)" in ops[0].comment
    chk.after(ops)

    d, ops = pay(d, ali, allocation=a407.pk)  # rest of that share
    assert len(ops) == 1 and ops[0].amount == 200000
    chk.after(ops)
    assert S.debt_allocation_paid(d)[a407.pk] == 300000

    d, ops = pay(d, ali)  # «Hammasi»: only the unpaid orders, in row order
    assert [o.order_ref for o in ops] == ["406", "408"]
    assert [o.amount for o in ops] == [200000, 500000]
    chk.after(ops)
    assert d.status == "closed" and S.debt_numbers(d)["remaining"] == 0
    assert Operation.objects.filter(debt=d).count() == 4
    assert S.balance(ali) == -1_000_000


def test_hammasi_on_fresh_split_debt_one_op_per_order(orders, members):
    _, ali, _ = members
    d = mk_split()
    chk = Check(d, ali)
    d, ops = pay(d, ali, amount=None)
    assert [o.order_ref for o in ops] == ["406", "407", "408"]
    assert [o.amount for o in ops] == [20, 30, 50]
    chk.after(ops)
    assert d.status == "closed"


# ------------------------------------------------------------------ 2. money, USD
def test_usd_split_exact_to_the_cent_and_wallet_equals_orders(orders, members, rate):
    _, ali, _ = members
    d = mk_split(currency="USD")
    assert d.currency == "USD" and d.orig_amount == 100
    a406, a407, a408 = (alloc(d, r) for r in ("406", "407", "408"))
    chk = Check(d, ali)

    d, ops = pay(d, ali, allocation=a407.pk, amount=D("10.01"))
    assert ops[0].orig_amount == D("10.01") and ops[0].rate == rate
    assert ops[0].amount == som(D("10.01") * rate)
    chk.after(ops)
    # a comment edit never changes the so'm of a USD leg (update_operation recomputes)
    S.update_operation(ops[0], {"comment": "izoh"})
    ops[0].refresh_from_db()
    assert ops[0].amount == som(D("10.01") * rate) and ops[0].orig_amount == D("10.01")

    d, ops = pay(d, ali, allocation=a407.pk, amount=D("0.33"))
    chk.after(ops)
    d, ops = pay(d, ali, allocation=a407.pk)
    assert ops[0].orig_amount == D("19.66")
    chk.after(ops)
    d, ops = pay(d, ali)
    assert [o.orig_amount for o in ops] == [D("20.00"), D("50.00")]
    chk.after(ops)
    assert d.status == "closed"
    live = Operation.objects.filter(debt=d, is_deleted=False)
    assert sum(o.orig_amount for o in live) == 100  # exact to the cent
    assert S.debt_paid(d) == 100
    # each leg is round(orig * rate), nothing pushed on a row
    for o in live:
        assert o.amount == som(o.orig_amount * rate)


def test_usd_thirds_hammasi_closes_exactly(orders, members, rate):
    _, ali, _ = members
    d = mk_split((("406", "33.33"), ("407", "33.33"), ("408", "33.34")), currency="USD")
    chk = Check(d, ali)
    d, ops = pay(d, ali)
    assert sum(o.orig_amount for o in ops) == D("100.00")
    chk.after(ops)
    assert d.status == "closed"


def test_usd_total_so_m_is_consistent_with_rate_snapshot(orders, members, rate):
    d = mk_split(currency="USD")
    assert d.amount == som(D("100") * rate) and d.rate == rate


# ------------------------------------------------------------------ 3. payment rule table
def test_rule_allocation_given_amount_above_remainder(orders, members):
    _, ali, _ = members
    d = mk_split()
    a = alloc(d, "406")
    with pytest.raises(ServiceError) as e:
        pay(d, ali, allocation=a.pk, amount=D("20.01"))
    assert "20" in str(e.value)  # names the remainder
    assert Operation.objects.filter(debt=d).count() == 0


def test_rule_amount_without_allocation_is_refused_and_writes_nothing(orders, members):
    _, ali, _ = members
    d = mk_split()
    before = S.balance(ali)
    with pytest.raises(ServiceError) as e:
        pay(d, ali, amount=D("10"))
    assert "Buyurtmani tanlang" in str(e.value) and e.value.field == "allocation"
    assert Operation.objects.filter(debt=d).count() == 0 and S.balance(ali) == before


def test_rule_foreign_unknown_and_paid_allocation(orders, members):
    _, ali, _ = members
    d = mk_split()
    other = mk_split((("406", "5"), ("409", "5")))
    for bad in (alloc(other, "409").pk, 99999999):
        with pytest.raises(ServiceError) as e:
            pay(d, ali, allocation=bad, amount=D("1"))
        assert e.value.field == "allocation"
    with pytest.raises(ServiceError):
        pay(d, ali, allocation="abc")
    with pytest.raises(ServiceError):
        pay(d, ali, allocation=True)
    a = alloc(d, "406")
    pay(d, ali, allocation=a.pk)
    with pytest.raises(ServiceError) as e:
        pay(d, ali, allocation=a.pk, amount=D("1"))
    assert e.value.field == "allocation"
    assert Operation.objects.filter(debt=d).count() == 1
    assert Operation.objects.filter(debt=other).count() == 0


def test_rule_zero_negative_amount_and_closed_debt(orders, members):
    _, ali, _ = members
    d = mk_split()
    a = alloc(d, "406")
    for bad in (D("0"), D("-1")):
        with pytest.raises(ServiceError):
            pay(d, ali, allocation=a.pk, amount=bad)
    d, _ = pay(d, ali)
    assert d.status == "closed"
    with pytest.raises(ServiceConflict):
        pay(d, ali, allocation=a.pk)
    with pytest.raises(ServiceConflict):
        pay(d, ali)


def test_rule_single_order_debt_unchanged(orders, members):
    _, ali, _ = members
    d = mk_single()
    a = alloc(d, "406")
    # allocation optional; a stray foreign allocation is still refused
    d, ops = pay(d, ali, amount=D("400000"))
    assert len(ops) == 1 and ops[0].order_ref == "406" and ops[0].debt_allocation_id == a.pk
    assert "(406)" not in ops[0].comment  # the tag is for split debts only
    d, ops = pay(d, ali, allocation=a.pk, amount=D("100000"))
    d, ops = pay(d, ali)  # the whole remainder, still one op
    assert len(ops) == 1 and ops[0].amount == 500000 and d.status == "closed"
    # pay_debt wrapper keeps returning the first op
    d2 = mk_split()
    _, op = S.pay_debt(d2, payer=ali, actor_admin=True)
    assert isinstance(op, Operation) and op.order_ref == "406"


def test_split_debt_with_no_order_category_is_refused(orders, members):
    _, ali, _ = members
    from accounting.models import FinanceCategory

    d = mk_split()
    FinanceCategory.objects.filter(code="material").update(no_order=True)
    with pytest.raises(ServiceError):
        pay(d, ali)
    assert Operation.objects.filter(debt=d).count() == 0


def test_payer_without_wallet_and_pay_before_debt_date(orders, members):
    from oauth.models import TelegramMember

    _, ali, _ = members
    nw = TelegramMember.objects.create(telegram_id=777, name="NW", role="staff", wallet_mode="off")
    d = mk_split()
    with pytest.raises(ServiceError):
        pay(d, nw)
    with pytest.raises(ServiceError):
        pay(d, ali, on_date=d.date - timedelta(days=1))
    assert Operation.objects.filter(debt=d).count() == 0


# ------------------------------------------------------------------ 4. delete / restore a payment
def test_delete_one_payment_reopens_only_that_share_and_restore_closes(orders, members):
    _, ali, _ = members
    d = mk_split()
    d, ops = pay(d, ali)
    assert d.status == "closed"
    op407 = next(o for o in ops if o.order_ref == "407")
    chk = Check(d, ali)
    S.delete_operation(op407)
    d = Debt.objects.get(pk=d.pk)
    assert d.status == "open" and d.closed_at is None
    assert S.debt_paid(d) == 70 and S.debt_numbers(d)["remaining"] == 30
    chk.before = snapshot(ali, chk.refs)
    # only that share is payable now
    for ref in ("406", "408"):
        with pytest.raises(ServiceError):
            pay(d, ali, allocation=alloc(d, ref).pk)
    d, ops2 = pay(d, ali)
    assert [o.order_ref for o in ops2] == ["407"] and ops2[0].amount == 30
    chk.after(ops2)
    assert d.status == "closed"


def test_restore_deleted_payment_closes_again(orders, members):
    _, ali, _ = members
    d = mk_split()
    d, ops = pay(d, ali)
    S.delete_operation(ops[1])
    assert Debt.objects.get(pk=d.pk).status == "open"
    S.restore_operation(Operation.objects.get(pk=ops[1].pk))
    d = Debt.objects.get(pk=d.pk)
    assert d.status == "closed" and S.debt_paid(d) == 100


def test_restore_is_refused_when_share_would_be_overpaid(orders, members):
    _, ali, _ = members
    d = mk_split()
    d, ops = pay(d, ali, allocation=alloc(d, "406").pk)
    S.delete_operation(ops[0])
    pay(d, ali, allocation=alloc(d, "406").pk)  # pays that share again
    with pytest.raises(ServiceError):
        S.restore_operation(Operation.objects.get(pk=ops[0].pk))
    assert Operation.objects.get(pk=ops[0].pk).is_deleted  # rolled back
    assert S.debt_paid(Debt.objects.get(pk=d.pk)) == 20


def test_restore_leg_whose_allocation_was_removed_is_refused(orders, members):
    _, ali, _ = members
    d = mk_split()
    d, ops = pay(d, ali, allocation=alloc(d, "406").pk)
    S.delete_operation(ops[0])
    # no live payments now: the split may be replaced and the 406 row dropped
    S.update_debt(d, {"allocations": split_rows(("407", "50"), ("408", "50"))})
    assert not DebtAllocation.objects.filter(debt=d, order_ref="406").exists()
    op = Operation.objects.get(pk=ops[0].pk)
    assert op.debt_allocation_id is None  # SET_NULL
    with pytest.raises(ServiceError):
        S.restore_operation(op)
    assert Operation.objects.get(pk=ops[0].pk).is_deleted
    assert S.debt_paid(Debt.objects.get(pk=d.pk)) == 0


def test_editing_a_leg_above_its_share_rolls_back(orders, members):
    _, ali, _ = members
    d = mk_split()
    d, ops = pay(d, ali, allocation=alloc(d, "406").pk, amount=D("10"))
    with pytest.raises(ServiceError):
        S.update_operation(ops[0], {"amount": D("21")})
    ops[0].refresh_from_db()
    assert ops[0].amount == 10
    S.update_operation(ops[0], {"amount": D("20")})  # up to the share is fine
    ops[0].refresh_from_db()
    assert ops[0].amount == 20


def test_edit_leg_cannot_change_its_order(orders, members):
    _, ali, _ = members
    d = mk_split()
    d, ops = pay(d, ali, allocation=alloc(d, "406").pk, amount=D("10"))
    with pytest.raises(ServiceError):
        S.update_operation(ops[0], {"order_ref": "407"})
    ops[0].refresh_from_db()
    assert ops[0].order_ref == "406"


# ------------------------------------------------------------------ 5. atomic «Hammasi», concurrency
def test_hammasi_failure_on_the_last_op_leaves_nothing(orders, members, monkeypatch):
    _, ali, _ = members
    d = mk_split()
    real = S.create_operation
    calls = {"n": 0}

    def flaky(**kw):
        calls["n"] += 1
        if calls["n"] == 3:
            raise ServiceError("boom")
        return real(**kw)

    monkeypatch.setattr(S, "create_operation", flaky)
    with pytest.raises(ServiceError):
        pay(d, ali)
    assert calls["n"] == 3
    assert Operation.objects.filter(debt=d).count() == 0
    assert S.balance(ali) == 0 and Debt.objects.get(pk=d.pk).status == "open"
    # nothing paid: each order still carries its unpaid share of the debt
    assert [spent(r) for r in ("406", "407", "408")] == [20, 30, 50]


def test_hammasi_failure_through_the_api_writes_nothing(orders, members, api, monkeypatch):
    boss, ali, _ = members
    d = mk_split()
    real = S.create_operation
    calls = {"n": 0}

    def flaky(**kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ServiceError("boom")
        return real(**kw)

    monkeypatch.setattr(S, "create_operation", flaky)
    c = api(VIEW, ADD, CHANGE, ALL)
    link(ali, c)
    r = c.post(f"{URL}{d.pk}/pay/", {"member": ali.pk}, format="json")
    assert r.status_code == 400
    assert Operation.objects.filter(debt=d).count() == 0


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_concurrent_double_pay_cannot_overpay(orders, members):
    _, ali, _ = members
    d = mk_split()
    a = alloc(d, "406")
    barrier = threading.Barrier(2)
    results = []

    def worker():
        try:
            barrier.wait(timeout=10)
            pay(Debt.objects.get(pk=d.pk), ali, allocation=a.pk)
            results.append("ok")
        except (ServiceError, ServiceConflict) as e:
            results.append(type(e).__name__)
        finally:
            connections.close_all()

    ts = [threading.Thread(target=worker) for _ in range(2)]
    [t.start() for t in ts]
    [t.join(30) for t in ts]
    assert sorted(results) == ["ServiceError", "ok"], results
    assert Operation.objects.filter(debt=d, is_deleted=False).count() == 1
    assert S.debt_allocation_paid(Debt.objects.get(pk=d.pk))[a.pk] == 20
    assert spent("406") == 20


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_concurrent_hammasi_and_chosen_pay_never_exceed_the_debt(orders, members):
    _, ali, _ = members
    d = mk_split()
    a = alloc(d, "408")
    barrier = threading.Barrier(2)
    out = []

    def run(kw):
        try:
            barrier.wait(timeout=10)
            pay(Debt.objects.get(pk=d.pk), ali, **kw)
            out.append("ok")
        except (ServiceError, ServiceConflict):
            out.append("refused")
        finally:
            connections.close_all()

    ts = [threading.Thread(target=run, args=(kw,)) for kw in ({}, {"allocation": a.pk})]
    [t.start() for t in ts]
    [t.join(30) for t in ts]
    fresh = Debt.objects.get(pk=d.pk)
    assert S.debt_paid(fresh) <= 100
    paid = S.debt_allocation_paid(fresh)
    for al in DebtAllocation.objects.filter(debt=d):
        assert paid.get(al.pk, 0) <= al.amount
    # paid legs + unpaid shares: the orders always carry the whole debt
    assert sum(spent(r) for r in ("406", "407", "408")) == 100


# ------------------------------------------------------------------ 6. validation
def bad(**kw):
    with pytest.raises(ServiceError) as e:
        mk_split(**kw)
    return e.value


def test_validation_sum_mismatch_and_amounts(orders):
    e = bad(allocations=split_rows(("406", "20"), ("407", "30")), amount=100)
    assert e.field == "allocations"
    bad(allocations=split_rows(("406", "60"), ("407", "50")), amount=100)
    for amt in ("0", "-5", "NaN", "Infinity", "abc", "", None, True, [], {}):
        e = bad(allocations=[{"ref": "406", "amount": amt}, {"ref": "407", "amount": "50"}])
        assert e.field == "allocations", amt
    assert Debt.objects.count() == 0


def test_validation_rounding_of_shares_is_exact(orders):
    # 3 shares of 33.333 are quantised to 33.33 -> sum 99.99 != 100
    bad(
        allocations=split_rows(("406", "33.333"), ("407", "33.333"), ("408", "33.333")),
        amount=100,
    )


@pytest.mark.parametrize("second", ["406", "#406", "0406", " 406 ", "00406"])
def test_validation_duplicate_in_every_alias_form(orders, second):
    e = bad(allocations=split_rows(("406", "50"), (second, "50")), amount=100)
    assert e.field == "allocations"
    assert Debt.objects.count() == 0


def test_validation_manual_order_case_insensitive_duplicate(orders):
    ManualOrder.objects.create(ref="SM-003", client="Qo'lda")
    e = bad(allocations=split_rows(("SM-003", "50"), ("sm-003", "50")), amount=100)
    assert e.field == "allocations"
    d = mk_split((("SM-003", "50"), ("406", "50")))  # a manual order is a valid share
    assert [a.order_ref for a in d.allocations.all()] == ["SM-003", "406"]
    d2 = mk_split((("sm-003", "50"), ("406", "50")))  # stored with the canonical ref
    assert d2.allocations.first().order_ref == "SM-003"


def test_validation_aliases_are_canonicalised_on_save(orders):
    d = mk_split((("#0406", "50"), ("407", "50")))
    assert [a.order_ref for a in d.allocations.all()] == ["406", "407"]
    assert d.order_ref == "406" and d.order_id == orders["406"].pk


def test_validation_unknown_order_and_too_many_and_malformed(orders):
    bad(allocations=split_rows(("406", "50"), ("99999", "50")), amount=100)
    bad(allocations=split_rows(("406", "50"), ("x" * 40, "50")), amount=100)
    rows = [{"ref": f"SM-{i:03d}", "amount": "1"} for i in range(11)]
    for r in [x["ref"] for x in rows]:
        ManualOrder.objects.create(ref=r)
    bad(allocations=rows, amount=11)
    ok = S.create_debt(
        creditor="c",
        item="i",
        category_code="material",
        allocations=rows[:10],
        amount=10,
        actor_admin=True,
    )
    assert ok.allocations.count() == 10
    for raw in (
        [],
        None,
        "406",
        {"ref": "406"},
        [None],
        ["406"],
        [{"amount": "50"}],
        [{"ref": ""}],
    ):
        with pytest.raises(ServiceError):
            S.create_debt(
                creditor="c",
                item="i",
                category_code="material",
                allocations=raw if raw is not None else [],
                amount=100,
                actor_admin=True,
            )
    for ref in (None, True, ["406"], {"a": 1}):
        bad(allocations=[{"ref": ref, "amount": "50"}, {"ref": "407", "amount": "50"}], amount=100)


def test_validation_both_or_neither_of_order_ref_and_allocations(orders):
    with pytest.raises(ServiceError):
        S.create_debt(
            creditor="c",
            item="i",
            category_code="material",
            order_ref="406",
            allocations=split_rows(("406", "100")),
            amount=100,
            actor_admin=True,
        )
    with pytest.raises(ServiceError):
        S.create_debt(
            creditor="c", item="i", category_code="material", amount=100, actor_admin=True
        )
    assert Debt.objects.count() == 0


def test_single_allocation_list_is_a_normal_single_order_debt(orders, members):
    _, ali, _ = members
    d = mk_split((("406", "100"),))
    d, ops = pay(d, ali, amount=D("40"))  # amount without allocation is fine: one order
    assert ops[0].order_ref == "406" and len(debt_rows([d])[0]["allocations"]) == 1


# ------------------------------------------------------------------ 7. update rules
def test_update_before_payments_replaces_keeps_matching_rows(orders):
    d = mk_split()
    keep_id = alloc(d, "407").pk
    d = S.update_debt(d, {"allocations": split_rows(("407", "60"), ("409", "40"))})
    refs = [a.order_ref for a in d.allocations.all()]
    assert sorted(refs) == ["407", "409"]
    assert alloc(d, "407").pk == keep_id and alloc(d, "407").amount == 60
    assert d.order_ref in refs  # mirror of the first row
    assert d.order_ref == d.allocations.order_by("id").first().order_ref


def test_update_total_with_new_allocations_before_payments(orders, rate):
    d = mk_split(currency="USD")
    d = S.update_debt(
        d, {"orig_amount": D("60"), "allocations": split_rows(("406", "10"), ("407", "50"))}
    )
    assert d.orig_amount == 60 and d.amount == som(D("60") * rate)
    assert sum(a.amount for a in d.allocations.all()) == 60


def test_update_split_total_or_order_ref_without_allocations_is_refused(orders):
    d = mk_split()
    with pytest.raises(ServiceError):
        S.update_debt(d, {"amount": 200})
    with pytest.raises(ServiceError):
        S.update_debt(d, {"order_ref": "409"})
    d.refresh_from_db()
    assert d.total_cur == 100 and d.allocations.count() == 3


def test_update_after_payment_split_is_frozen_identical_is_noop(orders, members):
    _, ali, _ = members
    d = mk_split()
    pay(d, ali, allocation=alloc(d, "406").pk, amount=D("5"))
    for payload in (
        {"allocations": split_rows(("406", "30"), ("407", "20"), ("408", "50"))},
        {"allocations": split_rows(("406", "20"), ("407", "30"))},
        {"amount": 200, "allocations": split_rows(("406", "40"), ("407", "60"), ("408", "100"))},
    ):
        with pytest.raises(ServiceError):
            S.update_debt(d, payload)
    ids = list(d.allocations.values_list("pk", flat=True))
    same = S.update_debt(
        d, {"allocations": split_rows(("406", "20.00"), ("407", "30"), ("408", "50"))}
    )
    assert list(same.allocations.values_list("pk", flat=True)) == ids
    S.update_debt(d, {"item": "yangi", "amount": 100})  # unchanged total, no allocations
    S.update_debt(d, {"item": "yangi 2"})
    d.refresh_from_db()
    assert d.item == "yangi 2" and d.allocations.count() == 3
    assert S.debt_paid(d) == 5
    with pytest.raises(ServiceError):
        S.update_debt(d, {"category_code": "oylik"})


def test_update_single_order_debt_allocation_follows_total_and_order(orders, members):
    _, ali, _ = members
    d = mk_single()
    d = S.update_debt(d, {"amount": 600000})
    assert alloc(d, "406").amount == 600000 and d.allocations.count() == 1
    d = S.update_debt(d, {"order_ref": "407"})
    assert d.order_ref == "407" and d.allocations.get().order_ref == "407"
    d, ops = pay(d, ali, amount=D("100000"))
    with pytest.raises(ServiceError):  # frozen once paid
        S.update_debt(d, {"order_ref": "408"})
    with pytest.raises(ServiceError):  # can't go under what is paid
        S.update_debt(d, {"amount": 50000})
    d = S.update_debt(d, {"amount": 300000})
    assert d.allocations.get().amount == 300000


def test_update_single_into_split_before_payments(orders):
    d = mk_single(amount=100)
    d = S.update_debt(d, {"allocations": split_rows(("406", "40"), ("407", "60"))})
    assert d.allocations.count() == 2 and d.order_ref == "406"


def test_delete_blocked_by_a_live_leg_and_allowed_after_deleting_it(orders, members):
    _, ali, _ = members
    d = mk_split()
    d, ops = pay(d, ali, allocation=alloc(d, "407").pk, amount=D("1"))
    assert not S.can_delete_debt(ali, Debt.objects.get(pk=d.pk), True)
    with pytest.raises(ServiceConflict):
        S.delete_debt(d)
    S.delete_operation(ops[0])
    S.delete_debt(Debt.objects.get(pk=d.pk))
    assert Debt.objects.get(pk=d.pk).is_deleted


def test_staff_two_day_edit_limit_and_delete_rule_unchanged(orders, members):
    boss, ali, vali = members
    d = mk_split(created_by=ali)
    Debt.objects.filter(pk=d.pk).update(created_at=timezone.now() - timedelta(days=3))
    d = Debt.objects.get(pk=d.pk)
    assert not S.can_modify_debt(ali, d, False) and S.can_modify_debt(boss, d, True)
    assert S.can_delete_debt(ali, d, False) and not S.can_delete_debt(vali, d, False)


def test_update_a_paid_up_deleted_debt_is_refused(orders):
    d = mk_split()
    S.delete_debt(d)
    with pytest.raises(ServiceError):
        S.update_debt(d, {"item": "x"})


# ------------------------------------------------------------------ 8. site API
def test_api_create_split_and_response_shape(orders, members, api, bot_events):
    _, ali, _ = members
    c = api(VIEW, ADD)
    link(ali, c)
    body = {
        "creditor": "X",
        "item": "Y",
        "category_code": "material",
        "currency": "USD",
        "orig_amount": "100",
        "allocations": [
            {"ref": "406", "amount": "20"},
            {"ref": "407", "amount": "30"},
            {"ref": "408", "amount": "50"},
        ],
    }
    S.set_usd_rate(12000)
    r = c.post(URL, body, format="json")
    assert r.status_code == 201, r.content
    j = r.json()
    assert j["order_ref"] == "406, 407, 408" and j["client"] == ""
    assert [a["amount"] for a in j["allocations"]] == ["20.00", "30.00", "50.00"]
    assert all(a["id"] for a in j["allocations"]) and j["total"] == "100.00"
    assert not bot_events.of("finance.debt_created")


def test_api_create_validation_400(orders, members, api):
    _, ali, _ = members
    c = api(VIEW, ADD)
    link(ali, c)
    base = {"creditor": "X", "item": "Y", "category_code": "material", "amount": "100"}
    two = [{"ref": "406", "amount": "50"}, {"ref": "407", "amount": "50"}]
    cases = [
        {**base, "allocations": two, "order_ref": "406"},  # both
        base,  # neither
        {**base, "allocations": [{"ref": "406", "amount": "50"}, {"ref": "407", "amount": "49"}]},
        {**base, "allocations": [{"ref": "406", "amount": "50"}, {"ref": "#406", "amount": "50"}]},
        {**base, "allocations": [{"ref": "406", "amount": "100"}, {"ref": "9999", "amount": "0"}]},
        {**base, "allocations": []},
        {**base, "allocations": [{"ref": "406", "amount": "NaN"}, {"ref": "407", "amount": "50"}]},
        {**base, "allocations": ["406"]},
    ]
    for body in cases:
        r = c.post(URL, body, format="json")
        assert r.status_code == 400, (body, r.content)
    assert Debt.objects.count() == 0


def test_api_pay_returns_operation_and_operations_and_one_event_per_op(
    orders, members, api, bot_events
):
    boss, ali, _ = members
    d = mk_split()
    c = api(VIEW, ADD, CHANGE, ALL)
    link(ali, c)
    r = c.post(f"{URL}{d.pk}/pay/", {"member": ali.pk}, format="json")
    assert r.status_code == 200, r.content
    j = r.json()
    assert len(j["operations"]) == 3 and j["operation"]["id"] == j["operations"][0]["id"]
    assert [o["order_ref"] for o in j["operations"]] == ["406", "407", "408"]
    assert j["debt"]["status"] == "closed"
    evs = bot_events.of("finance.operation_created")
    assert len(evs) == 3


def test_api_pay_rule_through_the_site(orders, members, api, bot_events):
    boss, ali, _ = members
    d = mk_split()
    c = api(VIEW, ADD, CHANGE, ALL)
    link(ali, c)
    a = alloc(d, "407")
    r = c.post(f"{URL}{d.pk}/pay/", {"member": ali.pk, "amount": "10"}, format="json")
    assert r.status_code == 400 and Operation.objects.count() == 0
    r = c.post(
        f"{URL}{d.pk}/pay/", {"member": ali.pk, "allocation": a.pk, "amount": "10"}, format="json"
    )
    assert r.status_code == 200 and len(r.json()["operations"]) == 1
    assert r.json()["operation"]["order_ref"] == "407"
    r = c.post(
        f"{URL}{d.pk}/pay/", {"member": ali.pk, "allocation": a.pk, "amount": "21"}, format="json"
    )
    assert r.status_code == 400 and "20" in str(r.json())
    r = c.post(f"{URL}{d.pk}/pay/", {"member": ali.pk, "allocation": 99999999}, format="json")
    assert r.status_code == 400
    assert len(bot_events.of("finance.operation_created")) == 1
    assert Operation.objects.count() == 1


def test_api_patch_rules(orders, members, api):
    boss, ali, _ = members
    d = mk_split(created_by=ali)
    c = api(VIEW, CHANGE)
    link(ali, c)
    u = f"{URL}{d.pk}/"
    assert c.patch(u, {"amount": "200"}, format="json").status_code == 400
    assert c.patch(u, {"order_ref": "407"}, format="json").status_code == 400
    r = c.patch(
        u,
        {"allocations": [{"ref": "406", "amount": "70"}, {"ref": "409", "amount": "30"}]},
        format="json",
    )
    assert r.status_code == 200, r.content
    assert [a["order_ref"] for a in r.json()["allocations"]] == ["406", "409"]
    pay(Debt.objects.get(pk=d.pk), ali, allocation=alloc(d, "406").pk, amount=D("1"))
    r = c.patch(
        u,
        {"allocations": [{"ref": "406", "amount": "50"}, {"ref": "409", "amount": "50"}]},
        format="json",
    )
    assert r.status_code == 400
    same = c.patch(
        u,
        {
            "amount": "100",
            "allocations": [{"ref": "406", "amount": "70"}, {"ref": "409", "amount": "30"}],
        },
        format="json",
    )
    assert same.status_code == 200
    assert c.patch(u, {"item": "z"}, format="json").status_code == 200  # no-op for shares


def test_api_patch_old_site_two_day_limit(orders, members, api):
    _, ali, _ = members
    d = mk_split(created_by=ali)
    Debt.objects.filter(pk=d.pk).update(created_at=timezone.now() - timedelta(days=3))
    c = api(VIEW, CHANGE, DELETE)
    link(ali, c)
    r = c.patch(
        f"{URL}{d.pk}/",
        {"allocations": [{"ref": "406", "amount": "70"}, {"ref": "409", "amount": "30"}]},
        format="json",
    )
    assert r.status_code == 403
    assert d.allocations.count() == 3
    assert c.delete(f"{URL}{d.pk}/").status_code == 204  # delete rule unchanged


def test_api_delete_blocked_by_live_leg_409(orders, members, api):
    boss, ali, _ = members
    d = mk_split(created_by=ali)
    pay(d, ali, allocation=alloc(d, "406").pk, amount=D("1"))
    c = api(VIEW, DELETE, superuser=False)
    link(ali, c)
    assert c.delete(f"{URL}{d.pk}/").status_code in (400, 409)
    assert not Debt.objects.get(pk=d.pk).is_deleted


def test_api_filter_and_search_find_split_debts_and_paid_not_multiplied(orders, members, api):
    boss, ali, _ = members
    d = mk_split()
    other = mk_single(order_ref="409")
    pay(d, ali, allocation=alloc(d, "407").pk, amount=D("10"))
    pay(d, ali, allocation=alloc(d, "408").pk, amount=D("5"))
    c = api(VIEW, ALL)
    for ref in ("406", "407", "408"):
        j = c.get(URL, {"order_ref": ref}).json()
        assert [x["number"] for x in j["results"]] == [d.number], ref
        assert j["results"][0]["paid"] == "15.00" and j["results"][0]["remaining"] == "85.00"
    assert [x["number"] for x in c.get(URL, {"order_ref": "409"}).json()["results"]] == [
        other.number
    ]
    j = c.get(URL, {"search": "408"}).json()
    assert [x["number"] for x in j["results"]] == [d.number]
    assert j["results"][0]["paid"] == "15.00"
    # paid is never multiplied by the allocation joins, also in the plain list / stats
    j = c.get(URL).json()
    row = next(x for x in j["results"] if x["number"] == d.number)
    assert row["paid"] == "15.00" and row["total"] == "100.00"
    assert S.debt_paid_annotated(S.debts_qs("all").get(pk=d.pk)) == 15
    assert S.debts_qs("all").filter(pk=d.pk).count() == 1
    st = c.get(URL + "stats/")
    assert st.status_code == 200


def test_debts_qs_filter_by_order_never_duplicates_rows(orders, members):
    _, ali, _ = members
    d = mk_split()
    pay(d, ali, allocation=alloc(d, "406").pk, amount=D("7"))
    qs = S.debts_with_order(S.debts_qs("all"), "40", contains=True)
    assert qs.count() == 1
    assert S.debt_paid_annotated(qs.get()) == 7


# ------------------------------------------------------------------ 9. order page
def order_url(ref):
    return f"/api/v1/finance/orders/{ref}/"


def test_order_page_shows_only_its_share(orders, members, api):
    boss, ali, _ = members
    d = mk_split(currency="USD") if S.set_usd_rate(12000) else None
    pay(d, ali, allocation=alloc(d, "407").pk, amount=D("10"))
    c = api("accounting.view_finance_orders", VIEW, ALL, "accounting.view_operation")
    j = c.get(order_url("407")).json()
    assert len(j["debts"]) == 1
    row = j["debts"][0]
    assert row["is_split"] is True and row["debt_total"] == "100.00"
    assert row["total"] == "30.00" and row["paid"] == "10.00" and row["remaining"] == "20.00"
    assert row["orig_amount"] == "30.00" and row["amount"] == "360000.00"
    assert row["order_ref"] == "407" and row["share_status"] == "open"
    assert [a["order_ref"] for a in row["allocations"]] == ["407"]
    blob = str(j["debts"])
    assert "406" not in blob and "408" not in blob  # siblings are not exposed
    r406 = c.get(order_url("406")).json()["debts"][0]
    assert r406["total"] == "20.00" and r406["paid"] == "0.00"
    assert r406["share_status"] == "open"
    # a fully paid share reads «closed» while the debt stays open
    pay(Debt.objects.get(pk=d.pk), ali, allocation=alloc(d, "406").pk)
    r406 = c.get(order_url("406")).json()["debts"][0]
    assert r406["share_status"] == "closed" and r406["remaining"] == "0.00"
    assert r406["status"] == "open"


def test_order_page_single_debt_unchanged(orders, members, api):
    mk_single(amount=500000)
    c = api("accounting.view_finance_orders", VIEW, ALL)
    row = c.get(order_url("406")).json()["debts"][0]
    assert row["is_split"] is False and row["total"] == "500000.00"
    assert row["debt_total"] == "500000.00" and row["share_status"] == "open"


def test_order_page_row_scope(orders, members, api):
    boss, ali, vali = members
    mine = mk_split(created_by=ali)
    theirs = mk_split(created_by=vali)
    base = ("accounting.view_finance_orders", VIEW)
    # staff without VIEW_ALL: only the debts the acting member wrote
    c = api("accounting.view_finance_orders", VIEW, ALL)  # needed to open the page at all
    assert len(c.get(order_url("406")).json()["debts"]) == 2
    c2 = api(*base, "accounting.view_all_operations")
    assert len(c2.get(order_url("406")).json()["debts"]) == 2
    # no VIEW_ALL: the page itself needs it (require_perm), so scope is enforced in the
    # helper: call it directly for the two staff cases
    from api.views.finance import _order_debts

    class Req:
        pass

    def req(user):
        r = Req()
        r.user = user
        return r

    info = S.order_info("406")
    u_ali = api(*base)
    link(ali, u_ali)
    got = _order_debts(req(User_with_member(u_ali.user)), info)
    assert [x["number"] for x in got] == [mine.number]
    u_free = api(*base)  # not linked to any member
    assert _order_debts(req(User_with_member(u_free.user)), info) == []
    u_all = api(*base, ALL)
    assert len(_order_debts(req(u_all.user), info)) == 2
    assert theirs.number not in [x["number"] for x in got]


def User_with_member(user):
    from oauth.models import User

    return User.objects.get(pk=user.pk)  # fresh copy: drops cached telegram_member


def test_order_page_without_view_debt_has_no_debts(orders, members, api):
    mk_split()
    c = api("accounting.view_finance_orders", ALL)
    assert c.get(order_url("406")).json()["debts"] == []


def test_order_page_unlinked_user_with_view_all_flag_off_gets_403_not_500(orders, members, api):
    mk_split()
    c = api("accounting.view_finance_orders", VIEW)
    assert c.get(order_url("406")).status_code == 403  # no VIEW_ALL: page is closed


# ------------------------------------------------------------------ 10. dto / query count
def test_dto_split_display_and_allocations(orders, members):
    _, ali, _ = members
    d = mk_split()
    pay(d, ali, allocation=alloc(d, "407").pk, amount=D("10"))
    row = debt_rows(list(S.debts_qs("all")))[0]
    assert row["order_ref"] == "406, 407, 408" and row["client"] == ""
    assert [
        (a["order_ref"], a["amount"], a["paid"], a["remaining"]) for a in row["allocations"]
    ] == [
        ("406", "20.00", "0.00", "20.00"),
        ("407", "30.00", "10.00", "20.00"),
        ("408", "50.00", "0.00", "50.00"),
    ]
    assert all(a["client"] for a in row["allocations"])
    assert row["paid"] == "10.00" and row["remaining"] == "90.00"


def test_dto_more_than_three_orders_shows_plus_n(orders):
    pairs = [(r, "10") for r in ("406", "407", "408", "409")]
    ManualOrder.objects.create(ref="SM-100")
    pairs.append(("SM-100", "10"))
    d = mk_split(tuple(pairs))
    row = debt_rows([S.debts_qs("all").get(pk=d.pk)])[0]
    assert row["order_ref"] == "406, 407, 408 +2"


def test_dto_single_debt_unchanged_shape(orders):
    d = mk_single()
    row = debt_rows([S.debts_qs("all").get(pk=d.pk)])[0]
    assert row["order_ref"] == "406" and row["client"]
    assert len(row["allocations"]) == 1 and row["allocations"][0]["amount"] == "1000000.00"


def test_query_count_is_bounded_by_not_the_number_of_debts(orders, members, api):
    _, ali, _ = members
    c = api(VIEW, ALL)

    def count():
        with CaptureQueriesContext(connection) as q:
            assert c.get(URL).status_code == 200
        return len(q)

    mk_split()
    base = count()
    for _ in range(6):
        d = mk_split()
        pay(d, ali, allocation=alloc(d, "407").pk, amount=D("1"))
    assert count() <= base + 2, (count(), base)


def test_bot_list_query_count_bounded(orders, members, bot_client):
    for _ in range(2):
        mk_split()

    def count():
        with CaptureQueriesContext(connection) as q:
            assert bot_client.get(BOT, actor=100).status_code == 200
        return len(q)

    base = count()
    for _ in range(6):
        mk_split()
    assert count() <= base + 2


# ------------------------------------------------------------------ 11. lazy allocation
def test_orm_debt_without_allocation_pays_and_shows_synthetic_row(orders, members):
    _, ali, _ = members
    d = Debt.objects.create(
        number=1,
        date=date.today(),
        creditor="c",
        item="i",
        amount=1000,
        currency="UZS",
        category=S.category("material"),
        order=orders["406"],
        order_ref="406",
    )
    assert d.allocations.count() == 0
    row = debt_rows([S.debts_qs("all").get(pk=d.pk)])[0]
    assert len(row["allocations"]) == 1 and row["allocations"][0]["id"] is None
    assert row["allocations"][0]["amount"] == "1000.00"
    # an `allocation` param cannot target the synthetic row (it has no id) ...
    with pytest.raises(ServiceError):
        pay(d, ali, allocation=123456, amount=D("10"))
    # ... and pay still works, creating the row lazily
    d, ops = pay(d, ali, amount=D("400"))
    assert d.allocations.count() == 1 and ops[0].debt_allocation_id == d.allocations.get().pk
    row = debt_rows([S.debts_qs("all").get(pk=d.pk)])[0]
    assert row["allocations"][0]["id"] == d.allocations.get().pk
    d, ops = pay(d, ali)
    assert d.status == "closed" and S.debt_paid(d) == 1000


def test_orm_usd_debt_lazy_allocation_uses_orig_amount(orders, members, rate):
    _, ali, _ = members
    d = Debt.objects.create(
        number=1,
        date=date.today(),
        creditor="c",
        item="i",
        amount=som(D("100") * rate),
        currency="USD",
        orig_amount=D("100"),
        rate=rate,
        category=S.category("material"),
        order=orders["406"],
        order_ref="406",
    )
    d, ops = pay(d, ali, amount=D("40"))
    assert d.allocations.get().amount == 100 and ops[0].orig_amount == 40
    d, _ = pay(d, ali)
    assert d.status == "closed"


def test_orm_debt_lazy_through_bot_pay_and_card(orders, members, bot_client):
    Debt.objects.create(
        number=1,
        date=date.today(),
        creditor="c",
        item="i",
        amount=1000,
        currency="UZS",
        category=S.category("material"),
        order=orders["406"],
        order_ref="406",
    )
    j = bot_client.get(BOT + "1/", actor=100).json()
    assert j["allocations"][0]["id"] is None
    r = bot_client.post(BOT + "1/pay/", actor=100, data={"amount_text": "400"})
    assert r.status_code == 200, r.content
    assert r.json()["debt"]["allocations"][0]["id"] is not None
    assert r.json()["debt"]["remaining"] == "600.00"


# ------------------------------------------------------------------ 12. checks()
def test_checks_do_not_flag_equal_legs_but_flag_a_real_duplicate(orders, members):
    boss, ali, _ = members
    d = mk_split((("406", "50000"), ("407", "50000")))
    pay(d, ali)  # two legs: same member, date, amount, category
    titles = [c["title"] for c in S.checks()]
    assert not [t for t in titles if "bir xil yozuv" in t]
    # a real duplicate: the same share paid twice in the same way
    d2 = mk_split((("406", "50000"), ("407", "50000")))
    a = alloc(d2, "406")
    pay(d2, ali, allocation=a.pk, amount=D("20000"))
    pay(d2, ali, allocation=a.pk, amount=D("20000"))
    assert [c for c in S.checks() if "bir xil yozuv" in c["title"]]


# ------------------------------------------------------------------ 13. bot channel (old-bot simulation)
def test_old_bot_list_card_show_ids_and_totals(orders, members, bot_client):
    d = mk_split(created_by=members[1])
    lst = bot_client.get(BOT, actor=100).json()
    row = next(x for x in (lst["rows"]) if x["number"] == d.number)
    assert row["order_ref"] == "406, 407, 408" and row["total"] == "100.00"
    card = bot_client.get(f"{BOT}{d.number}/", actor=100).json()
    assert card["order_ref"] == "406, 407, 408" and card["client"] == ""
    assert len(card["allocations"]) == 3 and card["remaining"] == "100.00"


def test_old_bot_partial_pay_on_split_debt_refused_nothing_written(
    orders, members, bot_client, bot_events
):
    d = mk_split(created_by=members[1])
    n = len(bot_events)
    bal = S.balance(members[0])
    r = bot_client.post(f"{BOT}{d.number}/pay/", actor=100, data={"amount_text": "10"})
    assert r.status_code == 400, r.content
    assert "Buyurtmani tanlang" in str(r.json())
    assert Operation.objects.count() == 0 and S.balance(members[0]) == bal
    assert len(bot_events) == n
    assert Debt.objects.get(pk=d.pk).status == "open"


def test_old_bot_full_pay_is_hammasi_and_delete_unchanged(orders, members, bot_client, bot_events):
    boss, ali, _ = members
    d = mk_split(created_by=ali)
    r = bot_client.post(f"{BOT}{d.number}/pay/", actor=100, data={"amount_text": ""})
    assert r.status_code == 200, r.content
    j = r.json()
    assert len(j["operations"]) == 3 and j["operation"]["number"] == j["operations"][0]["number"]
    assert j["debt"]["status"] == "closed" and j["balance"] == "-100.00"
    assert len(bot_events.of("finance.operation_created")) == 3
    # a closed debt with live payments cannot be deleted; an untouched one can
    assert bot_client.delete(f"{BOT}{d.number}/", actor=200).status_code in (400, 409)
    fresh = mk_split(created_by=ali)
    assert bot_client.delete(f"{BOT}{fresh.number}/", actor=200).status_code in (200, 204)
    assert Debt.objects.get(pk=fresh.pk).is_deleted


def test_bot_pay_with_allocation_and_rule_table(orders, members, bot_client, bot_events):
    d = mk_split(created_by=members[1])
    a = alloc(d, "408")
    r = bot_client.post(
        f"{BOT}{d.number}/pay/", actor=100, data={"amount_text": "20", "allocation": a.pk}
    )
    assert r.status_code == 200, r.content
    j = r.json()
    assert len(j["operations"]) == 1 and j["operation"]["order_ref"] == "408"
    assert j["debt"]["remaining"] == "80.00"
    over = bot_client.post(
        f"{BOT}{d.number}/pay/", actor=100, data={"amount_text": "31", "allocation": a.pk}
    )
    assert over.status_code == 400
    whole = bot_client.post(f"{BOT}{d.number}/pay/", actor=100, data={"allocation": a.pk})
    assert whole.status_code == 200 and whole.json()["operation"]["amount"] == "30.00"
    for junk in ("x", 0, -3, [1], {"a": 1}, "1e3"):
        resp = bot_client.post(f"{BOT}{d.number}/pay/", actor=100, data={"allocation": junk})
        assert resp.status_code == 400, junk
    assert len(bot_events.of("finance.operation_created")) == 2


def test_bot_pay_usd_amount_must_be_dollars(orders, members, bot_client, rate):
    d = mk_split(currency="USD", created_by=members[1])
    a = alloc(d, "406")
    r = bot_client.post(
        f"{BOT}{d.number}/pay/", actor=100, data={"amount_text": "5000", "allocation": a.pk}
    )
    assert r.status_code == 400
    ok = bot_client.post(
        f"{BOT}{d.number}/pay/", actor=100, data={"amount_text": "5.5$", "allocation": a.pk}
    )
    assert ok.status_code == 200 and ok.json()["operation"]["orig_amount"] == "5.50"


def test_bot_create_split_and_validation_never_500(orders, members, bot_client):
    base = {"creditor": "X", "item": "Y", "amount_text": "100$", "category": "material"}
    S.set_usd_rate(12000)
    ok = bot_client.post(
        BOT,
        actor=200,
        data={
            **base,
            "allocations": [{"ref": "406", "amount": "20"}, {"ref": "407", "amount": "80"}],
        },
    )
    assert ok.status_code == 201, ok.content
    j = ok.json()
    assert j["order_ref"] == "406, 407" and j["client"] == "" and len(j["allocations"]) == 2
    junk = [
        "x",
        5,
        [],
        [None],
        ["406"],
        [{"ref": "406"}],
        [{"ref": "406", "amount": "NaN"}, {"ref": "407", "amount": "100"}],
        [{"ref": "406", "amount": "abc"}, {"ref": "407", "amount": "100"}],
        [{"ref": ["x"], "amount": "100"}],
        [{"ref": "406", "amount": "50"}, {"ref": "0406", "amount": "50"}],
        [{"ref": "406", "amount": {"a": 1}}, {"ref": "407", "amount": "100"}],
    ]
    for raw in junk:
        r = bot_client.post(BOT, actor=200, data={**base, "allocations": raw})
        assert r.status_code == 400, (raw, r.status_code)
    both = bot_client.post(
        BOT,
        actor=200,
        data={**base, "order_ref": "406", "allocations": [{"ref": "406", "amount": "100"}]},
    )
    assert both.status_code == 400
    neither = bot_client.post(BOT, actor=200, data=base)
    assert neither.status_code == 400
    assert Debt.objects.count() == 1


def test_bot_parse_preview_matches_saved_amount(orders, members, bot_client, rate):
    r = bot_client.post("finance/parse/", actor=200, data={"text": "10.005$", "mode": "money"})
    assert r.status_code == 200, r.content
    shown = D(str(r.json()["orig"]))
    d = bot_client.post(
        BOT,
        actor=200,
        data={
            "creditor": "X",
            "item": "Y",
            "amount_text": "10.005$",
            "category": "material",
            "order_ref": "406",
        },
    ).json()
    assert D(d["total"]) == shown


# ------------------------------------------------------------------ 14. contract fixtures
def test_split_fixtures_match_real_responses(orders, members, bot_client, rate):
    d = mk_split(currency="USD", created_by=members[1])
    S.set_usd_rate(12050)
    card = bot_client.get(f"{BOT}{d.number}/", actor=100).json()
    fx = load_fixture("dto.debt.3.json")
    assert set(card) >= set(fx) - {"payments"}
    assert set(card["allocations"][0]) == set(fx["allocations"][0])
    req = load_fixture("misc.debt_pay_split_request.json")
    assert set(req) <= {"amount_text", "allocation"}
    resp = bot_client.post(f"{BOT}{d.number}/pay/", actor=100, data={})
    assert resp.status_code == 200
    fx_resp = load_fixture("misc.debt_pay_split_response.json")
    assert set(resp.json()) == set(fx_resp)
    assert set(resp.json()["operation"]) == set(fx_resp["operation"])
    assert shape(resp.json()["debt"]["allocations"]) == shape(fx_resp["debt"]["allocations"])
    create = load_fixture("misc.debt_create_split_request.json")
    assert "order_ref" not in create and isinstance(create["allocations"], list)
    S.set_usd_rate(12000)
    created = bot_client.post(BOT, actor=200, data=create)
    assert created.status_code == 201, created.content
    assert [a["order_ref"] for a in created.json()["allocations"]] == ["406", "407", "408"]


def test_single_order_pay_payload_unchanged(orders, members, bot_client):
    d = mk_single(created_by=members[1])
    r = bot_client.post(f"{BOT}{d.number}/pay/", actor=100, data={"amount_text": "400000"})
    assert r.status_code == 200
    assert set(r.json()) == {"debt", "operation", "operations", "balance"}
    assert len(r.json()["operations"]) == 1


def test_dto_fixture_keys_match_debt_dto(orders):
    d = mk_split()
    row = debt_dto(S.debts_qs("all").get(pk=d.pk), "")
    fx = load_fixture("dto.debt.3.json")
    assert set(row) == set(fx)


# ------------------------------------------------------------------ 15. migrations
@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_migration_0025_backfill_forward_and_reverse_rules(orders):
    from django.db.migrations.executor import MigrationExecutor

    cat = S.category("material")
    d1 = mk_single(amount=1000)
    d2 = mk_split()
    ex = MigrationExecutor(connection)
    try:
        # roll back to before the backfill: allocations stay (0025 reverse only guards)
        with pytest.raises(Exception):
            ex.migrate([("accounting", "0024_debtallocation")])  # d2 has 3 rows: refused
        assert DebtAllocation.objects.filter(debt=d2).count() == 3
        Debt.objects.filter(pk=d2.pk).delete()
        ex = MigrationExecutor(connection)
        ex.migrate([("accounting", "0024_debtallocation")])
        assert DebtAllocation.objects.filter(debt=d1).count() == 1  # reverse is a no-op
        DebtAllocation.objects.all().delete()
        Operation.objects.all().update(debt_allocation=None)
        ex = MigrationExecutor(connection)
        ex.migrate([("accounting", "0025_backfill_debt_allocations")])
        a = DebtAllocation.objects.get(debt=d1)
        assert a.order_ref == "406" and a.amount == 1000
    finally:
        ex = MigrationExecutor(connection)
        ex.migrate(ex.loader.graph.leaf_nodes())
    assert cat is not None


# ------------------------------------------------------------------ 16. review round: zero-sum legacy debt
def _zero_debt(by=None):
    """A pre-feature row with a non-positive sum: no allocation row can exist for it."""
    return Debt.objects.create(
        number=900,
        date=date.today(),
        creditor="Old",
        item="Zero",
        amount=0,
        category=S.category("material"),
        order_ref="406",
        created_by=by,
    )


def test_zero_sum_debt_pay_is_a_400_and_writes_nothing(orders, members):
    _, ali, _ = members
    d = _zero_debt(ali)
    with pytest.raises(ServiceError):
        pay(d, ali)
    assert not DebtAllocation.objects.filter(debt=d).exists()
    assert not Operation.objects.filter(debt=d).exists()


def test_zero_sum_debt_comment_patch_works_and_order_ref_follows(orders, members, api):
    _, ali, _ = members
    d = _zero_debt(ali)
    c = api(VIEW, CHANGE, ALL)
    r = c.patch(f"{URL}{d.pk}/", {"comment": "ok"}, format="json")
    assert r.status_code == 200, r.content
    assert r.json()["comment"] == "ok" and r.json()["order_ref"] == "406"
    assert not DebtAllocation.objects.filter(debt=d).exists()
    r = c.patch(f"{URL}{d.pk}/", {"order_ref": "407"}, format="json")
    assert r.status_code == 200, r.content
    assert Debt.objects.get(pk=d.pk).order_ref == "407"


def test_zero_sum_debt_found_by_filter_search_and_order_page(orders, members, api):
    d = _zero_debt()
    c = api(VIEW, "accounting.view_finance_orders", ALL)
    for q in ("?order_ref=406", "?search=406"):
        res = c.get(URL + q + "&status=all").json()["results"]
        assert [x["number"] for x in res] == [d.number], q
    od = c.get("/api/v1/finance/orders/406/").json()["debts"]
    assert [x["number"] for x in od] == [d.number]


def test_order_filter_lists_a_split_debt_once_and_finds_non_first_orders(orders, members, api):
    d = mk_split()
    c = api(VIEW, ALL)
    for ref in ("406", "407", "408"):
        res = c.get(f"{URL}?order_ref={ref}&status=all").json()["results"]
        assert [x["number"] for x in res] == [d.number], ref
    res = c.get(f"{URL}?search=407&status=all").json()["results"]
    assert [x["number"] for x in res] == [d.number]
    # the display text never reaches the column: it mirrors the first allocation
    assert Debt.objects.get(pk=d.pk).order_ref == "406"


def test_migration_0025_skips_a_zero_sum_debt(orders):
    from importlib import import_module

    mod = import_module("accounting.migrations.0025_backfill_debt_allocations")
    z = _zero_debt()
    ok = mk_single(amount=1000)
    DebtAllocation.objects.all().delete()
    from django.apps import apps

    mod.backfill(apps, None)
    assert not DebtAllocation.objects.filter(debt=z).exists()
    assert DebtAllocation.objects.filter(debt=ok).count() == 1


# ------------------------------------------------------------------ 17. checks(): exemption scope
def _dups():
    return [c for c in S.checks() if "bir xil yozuv" in c["title"]]


def test_checks_payment_plus_identical_manual_entry_is_flagged(orders, members):
    _, ali, _ = members
    d = mk_single(amount=500000)
    pay(d, ali, amount=D("500000"))
    S.create_operation(
        member=ali,
        kind="expense",
        amount=500000,
        category_code="material",
        order_ref="406",
        actor_admin=True,
    )
    assert _dups()


def test_checks_equal_payments_on_two_debts_are_flagged(orders, members):
    _, ali, _ = members
    for _ in range(2):
        pay(mk_single(amount=500000), ali, amount=D("500000"))
    assert _dups()


def test_checks_hammasi_legs_not_flagged_same_allocation_twice_flagged(orders, members):
    _, ali, _ = members
    d = mk_split((("406", "50000"), ("407", "50000")))
    pay(d, ali)
    assert not _dups()
    d2 = mk_split((("406", "50000"), ("407", "50000")))
    a = alloc(d2, "406")
    pay(d2, ali, allocation=a.pk, amount=D("10000"))
    pay(d2, ali, allocation=a.pk, amount=D("10000"))
    assert _dups()


# ------------------------------------------------------------------ order cost of a debt
def test_the_order_carries_the_debt_from_the_day_it_is_taken(orders, members):
    _, ali, _ = members
    d = mk_split((("406", "200000"), ("407", "300000")))
    # nothing paid yet: each order already costs its share
    assert spent("406") == 200000 and spent("407") == 300000
    assert S.order_stats("406")["debt"] == 200000
    d, _ = pay(d, ali, allocation=alloc(d, "407").pk, amount=D("100000"))
    assert spent("407") == 300000  # 100 000 paid + 200 000 still owed
    assert S.order_stats("407")["debt"] == 200000
    d, _ = pay(d, ali)
    assert d.status == "closed" and spent("406") == 200000 and spent("407") == 300000
    assert S.order_stats("407")["debt"] == 0
    # a deleted debt costs nothing
    d2 = mk_single(order_ref="408", amount=50000)
    assert spent("408") == 50000
    S.delete_debt(d2)
    assert spent("408") == 0
