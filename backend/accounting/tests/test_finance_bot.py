"""The finance bot end to end: Telegram updates in, DB rows and Bot API calls out."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from accounting import services as S
from accounting.finance.text import parse_amount, parse_money, parse_quick
from accounting.finance_models import (
    MoneyRequest,
    MonthReport,
    Operation,
    OrderBonus,
    SiteEntryTask,
)
from oauth.models import TelegramMember

from .conftest import Bot

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------- parsing (same as code.txt)
@pytest.mark.parametrize(
    "text,expected",
    [
        ("150000", 150000),
        ("150 000", 150000),
        ("150k", 150000),
        ("150 ming", 150000),
        ("1.5 mln", 1500000),
        ("1,5mln", 1500000),
        ("2 000 000 so'm", 2000000),
        ("4200.50", 4200),
        ("12.5", Decimal("12.5")),
        ("abc", None),
        ("0", None),
    ],
)
def test_parse_amount(text, expected):
    got = parse_amount(text)
    assert (got is None) if expected is None else got == Decimal(str(expected))


def test_parse_money_detects_dollars():
    assert parse_money("100$") == (Decimal("100"), "USD")
    assert parse_money("250 ming") == (Decimal("250000"), "UZS")


def test_parse_quick_entry(db):
    cats = S.categories()
    q = parse_quick("350000 furnitura 406 petlya", ["406"], cats)
    assert (
        q["kind"] == "expense"
        and q["cat"] == "furnitura"
        and q["ord"] == "406"
        and q["val"] == 350000
    )
    q = parse_quick("4200$ avans Назира 406", ["406"], cats)
    assert q["kind"] == "income" and q["cat"] == "avans" and q["cur"] == "USD"
    q = parse_quick("2000000 oylik Dilmurod", [], cats)
    assert q["cat"] == "oylik"


# ---------------------------------------------------------------- joining
def test_unknown_user_joins_with_moliya_and_admin_approves(tg, members):
    boss = members[0]
    new = Bot(555, "Sardor", "sardor")
    assert new.text("/start") is False  # plain /start keeps the site bot greeting
    assert new.text("/moliya") is True
    assert "join" in tg.buttons(555)
    new.press("join")
    m = TelegramMember.objects.get(telegram_id=555)
    assert m.role == "pending"
    assert "approve:555" in tg.buttons(boss.telegram_id)
    Bot(100).press("approve:555")
    m.refresh_from_db()
    assert m.role == "staff"


def test_unknown_user_random_text_is_left_to_the_site_bot(tg, db):
    assert Bot(777).text("salom") is False
    assert tg.calls == []


def test_site_linking_start_is_not_handled(tg, members):
    assert Bot(200).text("/start 15") is False


def test_group_chats_are_ignored(tg, members):
    from accounting.telegram.router import handle_update

    assert (
        handle_update(
            {
                "update_id": 99999,
                "message": {
                    "message_id": 1,
                    "from": {"id": 200},
                    "chat": {"id": -5, "type": "group"},
                    "text": "x",
                },
            }
        )
        is False
    )


def test_duplicate_update_is_handled_once(tg, members):
    from accounting.telegram.router import handle_update

    up = {
        "update_id": 424242,
        "message": {
            "message_id": 1,
            "from": {"id": 200, "first_name": "Ali"},
            "chat": {"id": 200, "type": "private"},
            "text": "/yordam",
        },
    }
    handle_update(up)
    n = len(tg.calls)
    assert handle_update(up) is True
    assert len(tg.calls) == n


# ---------------------------------------------------------------- expense flow
def test_quick_entry_creates_expense_on_site_order(tg, members, site_order):
    ali = Bot(200)
    ali.text("350000 furnitura 406 petlya")
    assert "save" in tg.buttons(200)  # straight to the confirm card
    ali.press("save")
    op = Operation.objects.get()
    assert (op.kind, op.amount, op.category.code, op.order_ref, op.order_id) == (
        "expense",
        Decimal("350000"),
        "furnitura",
        "406",
        site_order.id,
    )
    assert op.member.telegram_id == 200 and op.author.telegram_id == 200 and op.source == "bot"
    assert S.balance(op.member) == Decimal("-350000")
    assert any("Hamyoningiz manfiy" in t for t in tg.texts(200))


def test_step_by_step_expense_with_dollars(tg, members, site_order):
    ali = Bot(200)
    ali.text("➖ Chiqim")
    ali.text("100$")
    ali.press("cat:material")
    assert "ord:406" in tg.buttons(200)
    ali.press("ord:406")
    ali.text("LDSP 3 list")
    ali.press("save")
    op = Operation.objects.get()
    assert op.currency == "USD" and op.orig_amount == 100 and op.amount == Decimal("1200000")
    assert op.comment == "LDSP 3 list"


def test_salary_asks_worker_and_never_an_order(tg, members):
    boss = Bot(100)
    boss.text("➖ Chiqim")
    boss.text("2 mln")
    boss.press("cat:oylik")
    assert any(b.startswith("wg:") for b in tg.buttons(100))
    boss.press("wg:0")
    wk = [b for b in tg.buttons(100) if b.startswith("wk:")][0]
    boss.press(wk)
    boss.press("pay:Oylik")
    boss.text("oktabr")
    boss.press("save")
    op = Operation.objects.get()
    assert op.worker == "Dilmurod" and op.pay_type == "Oylik" and op.order_ref == ""


def test_staff_cannot_pick_admin_only_category(tg, members):
    ali = Bot(200)
    ali.text("➖ Chiqim")
    ali.text("10000")
    assert "cat:uy" not in tg.buttons(200)
    ali.press("cat:uy")
    assert S.member_by_tg(200).id and not Operation.objects.exists()


def test_cancel_deletes_flow_messages(tg, members):
    ali = Bot(200)
    ali.text("➖ Chiqim")
    ali.text("50000")
    tg.reset()
    ali.press("cancel")
    assert [m for m, _, _ in tg.calls].count("deleteMessage") >= 3
    assert S.member_by_tg(200) and not Operation.objects.exists()


def test_receipt_photo_with_caption(tg, members):
    Bot(200).photo("FILE9", "120000 ovqat tushlik")
    Bot(200).press("ord:-")
    Bot(200).press("save")
    op = Operation.objects.get()
    assert op.receipt_file_id == "FILE9" and op.category.code == "ovqat"


# ---------------------------------------------------------------- delete rules
def test_staff_deletes_own_recent_entry_but_not_old_one(tg, members):
    ali = members[1]
    op = S.create_operation(
        member=ali, author=ali, kind="expense", amount=1000, category_code="boshqa"
    )
    old = S.create_operation(
        member=ali,
        author=ali,
        kind="expense",
        amount=1000,
        category_code="boshqa",
        on_date=date.today() - timedelta(days=5),
        actor_admin=True,
    )
    Bot(200).text(f"/ochir {old.number}")
    assert "o'chira olmaysiz" in tg.last(200)
    Bot(200).text(f"/ochir {op.number}")
    Bot(200).press(f"delok:{op.number}")
    op.refresh_from_db()
    assert op.is_deleted


# ---------------------------------------------------------------- transfers, requests, giving
def test_transfer_between_staff_writes_both_sides(tg, members):
    ali, vali = Bot(200), members[2]
    ali.text("🔄 Xodimga pul berish")
    ali.press(f"trto:{vali.telegram_id}")
    ali.text("300000")
    ali.text("zapravkaga")
    ali.press("trok")
    out, inc = Operation.objects.order_by("number")
    assert (out.kind, inc.kind, out.category.code) == ("expense", "income", "otkazma")
    assert inc.pair_id == out.id and S.balance(vali) == 300000
    S.delete_operation(out)
    inc.refresh_from_db()
    assert inc.is_deleted  # both halves go


def test_money_request_given_by_boss(tg, members):
    ali = Bot(200)
    ali.text("🙏 Rahbardan pul so'rash")
    ali.text("500 ming")
    ali.text("406 ga LDSP")
    req = MoneyRequest.objects.get()
    assert req.amount == 500000 and req.status == "pending"
    assert f"rq_ok:{req.number}" in tg.buttons(100)
    Bot(100).press(f"rq_ok:{req.number}")
    req.refresh_from_db()
    assert req.status == "given" and req.operation.category.code == "rahbar"
    assert S.balance(members[1]) == 500000


def test_boss_give_money(tg, members):
    boss = Bot(100)
    boss.text("💸 Pul berish")
    boss.press("give:200")
    boss.text("1 mln")
    boss.press("skip:comment")
    boss.press("save")
    op = Operation.objects.get()
    assert (
        op.member.telegram_id == 200
        and op.author.telegram_id == 100
        and op.category.code == "rahbar"
    )
    assert any("Sizga pul berildi" in t for t in tg.texts(200))


def test_rahbar_income_is_not_company_income(tg, members):
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
        member=ali, author=ali, kind="expense", amount=200_000, category_code="ovqat"
    )
    S.create_operation(
        member=boss,
        author=boss,
        kind="expense",
        amount=50_000,
        category_code="uy",
        actor_admin=True,
    )
    sm = S.summary(None, None)
    assert (
        sm["income"] == 0
        and sm["expense"] == 200000
        and sm["given_to_staff"] == 1000000
        and sm["home"] == 50000
    )


# ---------------------------------------------------------------- month report
def test_month_report_submit(tg, members):
    ali = Bot(200)
    S.create_operation(member=members[1], kind="income", amount=1000, category_code="boshqa_kirim")
    ali.text("📤 Oylik hisob")
    ali.press("msub")
    rep = MonthReport.objects.get()
    assert rep.member.telegram_id == 200 and rep.balance == 1000


# ---------------------------------------------------------------- Готов, bonus, «Pul oldim»
def test_ready_order_card_and_collect_full(tg, members, site_order, monkeypatch):
    from accounting.telegram.bonus import hourly_orders

    monkeypatch.setattr("accounting.telegram.bonus.report_card_png", lambda v: b"png")
    from constance import config

    config.FIN_BONUS_SINCE = (date.today() - timedelta(days=1)).isoformat()
    site_order.status = "done"
    site_order.save()
    hourly_orders(ok_hour=True)
    bn = OrderBonus.objects.get(order_ref="406")
    assert bn.total == 1000 and bn.currency == "USD" and bn.status == "waiting"
    assert "bpaid:406" in tg.buttons(300)  # Vali is the bonus receiver
    vali = Bot(300)
    vali.press("bpaid:406")
    vali.press("bpf:406")  # took the whole rest (600$)
    bn.refresh_from_db()
    assert (
        bn.status == "done" and bn.percent == Decimal("0.5") and bn.bonus == Decimal("60000")
    )  # 1000$*12000*0.5%
    op = Operation.objects.get(category__code="qoldiq")
    assert op.member.telegram_id == 300 and op.orig_amount == 600
    assert SiteEntryTask.objects.filter(order_ref="406", is_done=False).exists()
    # boss gets the handover question; accepting moves the cash to the boss
    Bot(100).press(f"pqk:{op.number}")
    assert S.balance(members[2]) == 0
    assert S.balance(members[0]) == op.amount


def test_old_ready_orders_get_no_card(tg, members, site_order):
    from constance import config

    from accounting.telegram.bonus import hourly_orders

    config.FIN_BONUS_SINCE = (date.today() + timedelta(days=1)).isoformat()
    site_order.status = "done"
    site_order.save()
    hourly_orders(ok_hour=True)
    assert not OrderBonus.objects.exists()


# ---------------------------------------------------------------- views & roles
def test_info_and_wallets_views_render(tg, members, site_order):
    S.create_operation(member=members[1], kind="expense", amount=5000, category_code="ovqat")
    Bot(100).text("📊 Ma'lumot")
    assert any("Ma'lumot" in t for t in tg.texts(100))
    Bot(100).text("👛 Hamyonlar")
    assert "Ali" in tg.last(100)
    Bot(100).text("🔍 Tekshiruv")
    Bot(100).text("🧾 Buyurtmalar")
    assert "ocard:406" in tg.buttons(100)
    Bot(100).press("ocard:406")
    assert "406" in tg.last(100)
    Bot(200).text("💳 Hamyonim")


def test_task_only_member_gets_task_keyboard(tg, members):
    Bot(100).text("/saytchi")
    Bot(100).press("rol:is_site_entry:200")
    ali = TelegramMember.objects.get(telegram_id=200)
    assert ali.is_site_entry and ali.is_task_only and not ali.has_wallet
    Bot(200).text("➖ Chiqim")
    assert "kirim-chiqim kiritmaysiz" in tg.last(200)


def test_excel_from_bot(tg, members):
    S.create_operation(member=members[1], kind="expense", amount=5000, category_code="ovqat")
    Bot(100).press(f"xls:{date.today():%Y-%m}")
    assert any(m == "sendDocument" for m, _, _ in tg.calls)


def test_scheduler_runs_each_job_once(tg, members):
    from datetime import datetime

    from accounting.jobs import run_due

    at = datetime.combine(date.today(), datetime.min.time()).replace(hour=21)
    first = run_due(at)
    assert "admin" in first and "orders" in first
    assert run_due(at) == []


# ---------------------------------------------------------------- review fixes
def test_join_does_not_link_site_account_by_unverified_telegram_id(tg, members, make_staff):
    boss_user = make_staff(superuser=True, telegram_id=555)  # set by an unchecked /start <id>
    Bot(555).text("/moliya")
    Bot(555).press("join")
    assert TelegramMember.objects.get(telegram_id=555).user_id is None
    assert boss_user.telegram_member if hasattr(boss_user, "telegram_member") else True


def test_forged_callback_cannot_book_admin_only_category(tg, members):
    ali = Bot(200)
    ali.text("➖ Chiqim")
    ali.text("10000")
    ali.press("cat:uy")  # not on the keyboard, sent by hand
    assert not Operation.objects.exists()


def test_receipt_can_only_be_attached_to_own_entry(tg, members):
    boss = members[0]
    op = S.create_operation(
        member=boss,
        author=boss,
        kind="expense",
        amount=1000,
        category_code="ovqat",
        actor_admin=True,
    )
    Bot(200).press(f"rcpt:{op.number}")
    assert "chek qo'sha olmaysiz" in tg.last(200)


def test_transfer_to_blocked_member_is_ignored(tg, members):
    TelegramMember.objects.create(telegram_id=901, name="Blok", role="blocked")
    Bot(200).press("trto:901")
    assert S.member_by_tg(200) and not tg.texts(200, "sendMessage")


def test_webhook_dispatch_claims(tg, members):
    from accounting.telegram.router import claims

    def up(uid, text):
        return {
            "update_id": 1,
            "message": {
                "message_id": 1,
                "from": {"id": uid},
                "chat": {"id": uid, "type": "private"},
                "text": text,
            },
        }

    assert claims(up(200, "salom")) is True  # member
    assert claims(up(777, "salom")) is False  # stranger → site greeting
    assert claims(up(777, "/moliya")) is True
    assert claims(up(200, "/start 15")) is False  # site linking


def test_usd_rate_failure_is_cached(db, monkeypatch, settings):
    from constance import config
    from django.core.cache import cache

    cache.clear()
    config.FIN_USD_RATE = 0.0
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise OSError("down")

    monkeypatch.setattr("accounting.services.requests.get", boom)
    assert S.usd_rate() == Decimal(str(config.USD_CURRENCY))
    S.usd_rate()
    assert len(calls) == 1
    cache.clear()


def test_handover_rejects_non_collection_rows(tg, members):
    from core.exceptions import ServiceError

    boss, ali, _ = members
    op = S.create_operation(
        member=ali, author=ali, kind="expense", amount=1000, category_code="ovqat"
    )
    with pytest.raises(ServiceError):
        S.handover_drop(op)
    with pytest.raises(ServiceError):
        S.handover_accept(op, boss)


def test_dropped_handover_cannot_be_restored(tg, members):
    from core.exceptions import ServiceError

    _, ali, _ = members
    op = S.create_operation(
        member=ali,
        author=ali,
        kind="income",
        amount=1000,
        category_code="qoldiq",
        comment="Pul oldim (mijozdan qoldiq)",
        internal=True,
    )
    S.handover_drop(op)
    with pytest.raises(ServiceError):
        S.restore_operation(Operation.objects.get(pk=op.pk))


def test_transfer_kind_cannot_be_edited(tg, members):
    from core.exceptions import ServiceError

    _, ali, vali = members
    out, inc = S.create_transfer(sender=ali, receiver=vali, amount=1000)
    with pytest.raises(ServiceError):
        S.update_operation(out, {"category_code": "ovqat"}, actor_admin=True)
    S.update_operation(out, {"amount": 2000}, actor_admin=True)
    inc.refresh_from_db()
    assert inc.amount == 2000
