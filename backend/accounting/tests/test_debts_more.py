"""«Qarzlar» fix loop: deleted debts, zero amounts, task-only reads, can_* perms, dates."""

from datetime import timedelta

import pytest

from accounting import services as S
from accounting.models import Debt, FinanceCategory, Operation
from accounting.text import today
from core.exceptions import ServiceError
from oauth.models import TelegramMember

pytestmark = pytest.mark.django_db

URL = "/api/v1/finance/debts/"
VIEW, ADD = "accounting.view_operation", "accounting.add_operation"
CHANGE, DELETE = "accounting.change_operation", "accounting.delete_operation"


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


def link(member, client):
    member.user = client.user
    member.save()


def test_restore_payment_of_deleted_debt_refused(site_order, members):
    _, ali, _ = members
    d = mk()
    d, op = S.pay_debt(d, payer=ali, amount=100000)
    S.delete_operation(op)
    S.delete_debt(Debt.objects.get(pk=d.pk))
    with pytest.raises(ServiceError):
        S.restore_operation(Operation.objects.get(pk=op.pk))
    assert Operation.objects.get(pk=op.pk).is_deleted


def test_pay_zero_refused(site_order, members, api):
    _, ali, _ = members
    d = mk(created_by=ali)
    with pytest.raises(ServiceError):
        S.pay_debt(d, payer=ali, amount=0)
    c = api(VIEW, ADD)
    link(ali, c)
    r = c.post(f"{URL}{d.pk}/pay/", {"member": ali.pk, "amount": "0"}, format="json")
    assert r.status_code == 400
    assert not Operation.objects.filter(debt=d).exists()


def test_bot_task_only_cannot_read(site_order, members, bot_client):
    TelegramMember.objects.create(telegram_id=503, name="NW", role="staff", wallet_mode="off")
    d = mk(created_by=members[1])
    assert bot_client.get("finance/debts/", actor=503).status_code == 403
    assert bot_client.get(f"finance/debts/{d.number}/", actor=503).status_code == 403
    assert bot_client.get(f"finance/debts/{d.number}/", actor=200).status_code == 200


def test_can_flags_need_operation_perms(site_order, members, api):
    _, ali, _ = members
    d = mk(created_by=ali, actor_admin=False)
    c = api(VIEW)
    link(ali, c)
    j = c.get(f"{URL}{d.pk}/").json()
    assert j["can_change"] is False and j["can_delete"] is False
    c2 = api(VIEW, CHANGE, DELETE)
    link(ali, c2)
    j = c2.get(f"{URL}{d.pk}/").json()
    assert j["can_change"] is True and j["can_delete"] is True


def test_site_create_needs_wallet_for_non_admin(site_order, members, api):
    nw = TelegramMember.objects.create(telegram_id=503, name="NW", role="staff", wallet_mode="off")
    c = api(VIEW, ADD)
    link(nw, c)
    body = {
        "creditor": "X",
        "item": "Y",
        "category_code": "material",
        "order_ref": "406",
        "amount": "500000",
    }
    assert c.post(URL, body, format="json").status_code == 400
    assert Debt.objects.count() == 0


def test_payment_date_not_before_debt_date(site_order, members):
    _, ali, _ = members
    d = mk(on_date=today() - timedelta(days=1))
    d, op = S.pay_debt(d, payer=ali, amount=100000)
    with pytest.raises(ServiceError):
        S.update_operation(
            Operation.objects.get(pk=op.pk), {"date": d.date - timedelta(days=1)}, actor_admin=True
        )


def test_debt_date_not_after_first_payment(site_order, members):
    _, ali, _ = members
    d = mk(on_date=today() - timedelta(days=3))
    d, _ = S.pay_debt(d, payer=ali, amount=100000, on_date=today() - timedelta(days=2))
    with pytest.raises(ServiceError):
        S.update_debt(d, {"date": today() - timedelta(days=1)}, actor_admin=True)
    assert S.update_debt(d, {"date": today() - timedelta(days=2)}, actor_admin=True)


def test_category_with_debts_cannot_be_deleted(site_order, members, api):
    cat = FinanceCategory.objects.create(code="qz_test", name="QZ", kind="expense")
    mk(category_code="qz_test")
    r = api(superuser=True).delete(f"/api/v1/finance/categories/{cat.pk}/")
    assert r.status_code == 400
    assert FinanceCategory.objects.filter(pk=cat.pk).exists()
