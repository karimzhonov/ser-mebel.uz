"""Moliya → Sozlamalar → Telegram: «Hamyon» can be set by hand (auto / on / off)."""

from decimal import Decimal

import pytest

from oauth.models import TelegramMember, TelegramRole, WalletMode

pytestmark = pytest.mark.django_db


def mk(**kw):
    kw.setdefault("telegram_id", 880000 + TelegramMember.objects.count())
    kw.setdefault("name", "A'zo")
    kw.setdefault("role", TelegramRole.STAFF)
    return TelegramMember.objects.create(**kw)


def test_auto_keeps_the_old_rule():
    assert mk().has_wallet
    feedback = mk(is_feedback=True)
    assert feedback.is_task_only and not feedback.has_wallet
    boss = mk(role=TelegramRole.ADMIN, is_site_entry=True)
    assert boss.has_wallet and not boss.is_task_only
    assert not mk(role=TelegramRole.PENDING).has_wallet


def test_on_gives_a_wallet_despite_duties():
    m = mk(is_site_entry=True, wallet_mode=WalletMode.ON)
    assert m.has_wallet and not m.is_task_only


def test_off_removes_the_wallet():
    m = mk(wallet_mode=WalletMode.OFF)
    assert not m.has_wallet and m.is_task_only
    boss = mk(role=TelegramRole.ADMIN, wallet_mode=WalletMode.OFF)
    # a walletless boss still books into other people's wallets
    assert not boss.has_wallet and not boss.is_task_only


def test_wallets_list_follows_the_mode():
    from accounting.services import wallets

    on = mk(is_feedback=True, wallet_mode=WalletMode.ON)
    off = mk(wallet_mode=WalletMode.OFF)
    ids = {m.pk for m in wallets()}
    assert on.pk in ids and off.pk not in ids


def test_api_switches_the_mode(admin_api):
    m = mk()
    r = admin_api.patch(f"/api/v1/finance/members/{m.pk}/", {"wallet_mode": "off"}, format="json")
    assert r.status_code == 200, r.data
    assert r.data["wallet_mode"] == "off" and r.data["has_wallet"] is False
    assert r.data["is_task_only"] is True
    r = admin_api.patch(f"/api/v1/finance/members/{m.pk}/", {"wallet_mode": "on"}, format="json")
    assert r.status_code == 200 and r.data["has_wallet"] is True
    assert (
        admin_api.patch(
            f"/api/v1/finance/members/{m.pk}/", {"wallet_mode": "maybe"}, format="json"
        ).status_code
        == 400
    )


def test_api_refuses_to_drop_a_wallet_with_money(admin_api, monkeypatch):
    import accounting.services as S

    m = mk()
    monkeypatch.setattr(S, "balance", lambda member, until=None: Decimal("150000"))
    r = admin_api.patch(f"/api/v1/finance/members/{m.pk}/", {"wallet_mode": "off"}, format="json")
    assert r.status_code == 400
    assert "qoldiq" in str(r.data["wallet_mode"])
    m.refresh_from_db()
    assert m.wallet_mode == WalletMode.AUTO
    # other edits (blocking, duties) are not held back by the balance
    r = admin_api.patch(f"/api/v1/finance/members/{m.pk}/", {"role": "blocked"}, format="json")
    assert r.status_code == 200


def test_bot_dto_reports_the_effective_wallet():
    from accounting.dto import member_dto

    d = member_dto(mk(is_feedback=True, wallet_mode=WalletMode.ON))
    assert d["has_wallet"] is True and d["is_task_only"] is False


def test_walletless_admin_cannot_book_into_himself():
    from accounting.services import create_operation_as
    from core.exceptions import ServiceError

    boss = mk(role=TelegramRole.ADMIN, wallet_mode=WalletMode.OFF)
    staff = mk()
    with pytest.raises(ServiceError, match="hamyoningiz yo'q"):
        create_operation_as(boss, boss, kind="expense", amount=1000, category_code="x")
    off = mk(wallet_mode=WalletMode.OFF)
    with pytest.raises(ServiceError, match="hamyoni yo'q"):
        create_operation_as(boss, off, kind="expense", amount=1000, category_code="x")
    assert staff.has_wallet  # the boss still books into a colleague with a wallet


def test_site_refuses_an_operation_for_a_walletless_member(admin_api):
    off = mk(wallet_mode=WalletMode.OFF)
    r = admin_api.post(
        "/api/v1/finance/operations/",
        {"member": off.pk, "kind": "expense", "category_code": "x", "amount": 1000},
        format="json",
    )
    assert r.status_code == 400 and "member" in r.data
