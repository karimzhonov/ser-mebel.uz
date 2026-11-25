"""Payroll stage 2: an approved salary sheet costs the clients (no wallet move), and
the «Oylik» payments made in the bot pay the worker's oldest approved sheets first."""

from datetime import date
from decimal import Decimal

import pytest
from constance import config

from accounting import services as S
from accounting.models import ManualOrder, Operation, Worker
from payroll.models import SheetCost

pytestmark = pytest.mark.django_db

URL = "/api/v1/finance/salary-sheets/"


@pytest.fixture(autouse=True)
def _rate(db):
    config.FIN_USD_RATE = 12000.0


@pytest.fixture
def orders(db):
    ManualOrder.objects.create(ref="370", client="Ulug'bek", price=30_000_000)
    ManualOrder.objects.create(ref="378", client="Akbar", price=10_000_000)
    return ["370", "378"]


@pytest.fixture
def people(db):
    d = Worker.objects.create(group="Sborka", name="Dilmurod", position="Usta")
    j = Worker.objects.create(group="Sborka", name="Jamshid", position="Usta")
    o = Worker.objects.create(group="Ofis", name="Umid", position="Hisobchi")
    return d, j, o


def pay(members, name, amount, on, pay_type="Oylik"):
    return S.create_operation(
        member=members[0],
        kind="expense",
        amount=amount,
        category_code="oylik",
        worker=name,
        pay_type=pay_type,
        on_date=on,
        actor_admin=True,
    )


def approved(client, worker, kind, month="2026-10", **body):
    r = client.post(URL, {"worker": worker.pk, "kind": kind, "month": month}, format="json")
    assert r.status_code == 201, r.data
    sid = r.data["id"]
    r = client.patch(f"{URL}{sid}/", body, format="json")
    assert r.status_code == 200, r.data
    r = client.post(f"{URL}{sid}/approve/")
    assert r.status_code == 200, r.data
    return r.data


def spent(ref):
    return S.order_stats(ref)["spent"]


# ---------------------------------------------------------------- client costs
def test_approval_books_each_id_and_splits_car_money_by_order_sum_without_a_wallet_move(
    admin_api, people, orders
):
    dil = people[0]
    ops_before = Operation.objects.count()
    s = approved(
        admin_api,
        dil,
        "sborka",
        lines=[
            {"section": "job", "order_ref": "370", "amount": "4000000"},
            {"section": "job", "order_ref": "378", "amount": "1000000"},
            {"section": "car", "title": "Benzin", "amount": "1000000"},
        ],
    )
    # 30 mln vs 10 mln contract: the car money goes 3 : 1
    assert spent("370") == Decimal("4750000")
    assert spent("378") == Decimal("1250000")
    st = S.order_stats("370")
    assert st["cats"]["oylik"] == Decimal("4750000")
    assert [r["source"] for r in st["payroll_rows"]] == ["car", "line"]
    bulk = S.order_stats_bulk(["370", "378"])
    assert bulk["370"]["spent"] == Decimal("4750000") and bulk["378"]["spent"] == Decimal("1250000")
    assert Operation.objects.count() == ops_before  # no wallet moved
    assert sum(Decimal(c["amount"]) for c in s["costs"]) == Decimal("6000000")
    assert {c["client"] for c in s["costs"]} == {"Ulug'bek", "Akbar"}

    card = admin_api.get("/api/v1/finance/orders/370/")
    assert card.status_code == 200
    assert card.data["spent"] == 4_750_000
    assert {r["number"] for r in card.data["payroll"]} == {s["number"]}

    # returned → the clients carry nothing until it is approved again
    r = admin_api.post(f"{URL}{s['id']}/return/", {"reason": "Qayta hisob"})
    assert r.status_code == 200
    assert spent("370") == 0 and not SheetCost.objects.exists()
    assert admin_api.post(f"{URL}{s['id']}/approve/").status_code == 200
    assert spent("370") == Decimal("4750000")  # booked once, not twice


def test_car_money_paid_from_a_wallet_with_an_id_is_not_counted_twice(
    admin_api, people, members, orders
):
    def car_op(who, ref, amount, on):
        return S.create_operation(
            member=members[0],
            kind="expense",
            amount=amount,
            category_code="mashina",
            worker=who,
            order_ref=ref,
            on_date=on,
            actor_admin=True,
        )

    car_op("Dilmurod", "370", 1_000_000, date(2026, 10, 15))  # the sheet's car money
    car_op("Gazel", "370", 300_000, date(2026, 10, 15))  # a real delivery: counts
    approved(
        admin_api,
        people[0],
        "sborka",
        lines=[
            {"section": "job", "order_ref": "370", "amount": "4000000"},
            {"section": "job", "order_ref": "378", "amount": "1000000"},
            {"section": "car", "amount": "1000000"},
        ],
    )
    # 4 mln job + 750 000 of the split car money + the 300 000 delivery
    assert spent("370") == Decimal("5050000")
    assert S.order_stats_bulk(["370"])["370"]["spent"] == Decimal("5050000")
    assert spent("378") == Decimal("1250000")


def test_every_id_percent_goes_to_its_client_fixed_does_not(admin_api, people, orders):
    # MENEJER: 1 % of a $10 000 order at 12 000 = 1 200 000 on that client
    approved(
        admin_api,
        people[2],
        "menejer",
        fixed="3000000",
        bonus_percent="1",
        lines=[{"section": "taken", "order_ref": "378", "amount": "10000"}],
    )
    assert spent("378") == Decimal("1200000")
    assert spent("370") == 0


def test_car_money_is_split_equally_when_no_contract_sum_is_known(admin_api, people, orders):
    ManualOrder.objects.update(price=0)
    approved(
        admin_api,
        people[0],
        "sborka",
        lines=[
            {"section": "job", "order_ref": "370", "amount": "100"},
            {"section": "job", "order_ref": "378", "amount": "100"},
            {"section": "car", "amount": "1001"},
        ],
    )
    car = dict(SheetCost.objects.filter(source="car").values_list("order_ref", "amount"))
    assert sum(car.values()) == Decimal("1001")
    assert sorted(car.values()) == [Decimal("500.50"), Decimal("500.50")]


def test_fixed_salary_stays_off_the_orders(admin_api, people, orders):
    approved(admin_api, people[2], "oddiy", fixed="3000000")
    assert not SheetCost.objects.exists()


def test_who_earned_how_much_stays_with_those_who_may_see_salaries(api, admin_api, people, orders):
    from accounting import dto as DTO

    approved(
        admin_api, people[0], "sborka", lines=[{"section": "job", "order_ref": "370", "amount": "4000000"}]
    )
    # the site's order card: the total is in «spent», the per-sheet rows need the sheets
    finance = api("accounting.view_finance_orders", "accounting.view_all_operations")
    card = finance.get("/api/v1/finance/orders/370/")
    assert card.status_code == 200, card.data
    assert card.data["spent"] == 4_000_000 and card.data["payroll"] == []
    assert len(admin_api.get("/api/v1/finance/orders/370/").data["payroll"]) == 1
    # the bot's order card: staff never see the wage, finance admins do
    info, st = S.order_info("370"), S.order_stats("370")
    staff = DTO.order_card_dto(info, st, full=False)["stats"]
    assert Decimal(staff["spent"]) == 0 and all(c["code"] != "oylik" for c in staff["cats"])
    boss = DTO.order_card_dto(info, st, full=True)["stats"]
    assert Decimal(boss["spent"]) == 4_000_000


def test_a_salary_payment_cannot_be_moved_onto_an_order(people, members, orders):
    op = pay(members, "Umid", 100_000, date(2026, 11, 3))
    op = S.update_operation(op, {"order_ref": "370"}, actor_admin=True)
    assert op.order_ref == "" and op.order_id is None


# ---------------------------------------------------------------- owed / paid
def test_oylik_payments_pay_the_oldest_sheet_first_and_carry_over(
    admin_api, people, members, orders
):
    umid = people[2]  # no pay day: the salary is for the calendar month
    sep = approved(admin_api, umid, "oddiy", month="2026-09", fixed="3000000")
    octo = approved(admin_api, umid, "oddiy", month="2026-10", fixed="2000000")

    early = pay(members, "Umid", 500_000, date(2026, 9, 10))  # an older (Excel) salary
    pay(members, "Umid", 2_000_000, date(2026, 10, 2))
    pay(members, "Umid", 700_000, date(2026, 10, 5), pay_type="Avans")  # not a payment here
    pay(members, "Boshqa", 9_000_000, date(2026, 10, 5))  # someone else
    last = pay(members, "Umid", 1_500_000, date(2026, 11, 3))

    a = admin_api.get(f"{URL}{sep['id']}/").data["payment"]
    assert a["status"] == "paid" and Decimal(a["paid"]) == 3_000_000 and Decimal(a["left"]) == 0
    assert [Decimal(p["amount"]) for p in a["payments"]] == [2_000_000, 1_000_000]
    assert early.number not in {p["number"] for p in a["payments"]}
    b = admin_api.get(f"{URL}{octo['id']}/").data["payment"]
    assert b["status"] == "partial" and Decimal(b["left"]) == 1_500_000
    assert [p["number"] for p in b["payments"]] == [last.number]

    rows = {r["id"]: r["pay"] for r in admin_api.get(URL).data["results"]}
    assert rows[sep["id"]]["status"] == "paid" and rows[octo["id"]]["status"] == "partial"

    # a deleted payment is followed at once (nothing is stored)
    last.is_deleted = True
    last.save()
    a = admin_api.get(f"{URL}{sep['id']}/").data["payment"]
    assert a["status"] == "partial" and Decimal(a["left"]) == 1_000_000
    assert admin_api.get(f"{URL}{octo['id']}/").data["payment"]["status"] == "unpaid"


def test_payment_too_early_for_any_sheet_is_shown_as_loose(admin_api, people, members, orders):
    umid = people[2]
    s = approved(admin_api, umid, "oddiy", month="2026-10", fixed="1000000")
    pay(members, "Umid", 400_000, date(2026, 10, 10))  # 3 weeks before the pay day
    p = admin_api.get(f"{URL}{s['id']}/").data["payment"]
    assert p["status"] == "unpaid"
    assert [Decimal(x["amount"]) for x in p["loose"]] == [400_000]


def test_sborka_team_money_paid_to_the_bosh_usta_pays_the_whole_sheet(
    admin_api, people, members, orders
):
    dil, jam, _ = people
    s = approved(
        admin_api,
        dil,
        "sborka",
        members=[{"worker": dil.pk, "share": "60"}, {"worker": jam.pk, "share": "40"}],
        lines=[{"section": "job", "order_ref": "370", "amount": "10000000"}],
    )
    pay(members, "Dilmurod", 8_000_000, date(2026, 11, 1))  # more than his 60 % share
    p = admin_api.get(f"{URL}{s['id']}/").data["payment"]
    assert p["status"] == "partial" and Decimal(p["paid"]) == 8_000_000 and p["loose"] == []
    pay(members, "Jamshid", 2_500_000, date(2026, 11, 2))  # a partner pays the rest
    p = admin_api.get(f"{URL}{s['id']}/").data["payment"]
    assert p["status"] == "paid" and Decimal(p["left"]) == 0
    assert [Decimal(x["amount"]) for x in p["loose"]] == [500_000]


def test_money_booked_to_the_whole_team_in_the_bot_counts_for_the_sborka_sheet(
    admin_api, people, members, orders
):
    dil, jam, _ = people  # both in group «Sborka»
    team = "👥 Sborka (butun komanda)"  # what the bot writes for «butun komanda»
    pay(members, team, 1_000_000, date(2026, 10, 5), pay_type="Avans")
    s = approved(
        admin_api,
        dil,
        "sborka",
        members=[{"worker": dil.pk, "share": "60"}, {"worker": jam.pk, "share": "40"}],
        lines=[{"section": "job", "order_ref": "370", "amount": "10000000"}],
    )
    assert Decimal(s["totals"]["advances_total"]) == 1_000_000  # the team advance
    pay(members, team, 9_000_000, date(2026, 11, 1))
    p = admin_api.get(f"{URL}{s['id']}/").data["payment"]
    assert p["status"] == "paid" and p["loose"] == []
    owed = admin_api.get(f"{URL}owed/", {"worker": team}).data
    assert owed["sheets"] == []


def test_the_payment_form_sees_how_much_is_still_owed(api, admin_api, people, members, orders):
    umid = people[2]
    sep = approved(admin_api, umid, "oddiy", month="2026-09", fixed="3000000")
    octo = approved(admin_api, umid, "oddiy", month="2026-10", fixed="2000000")
    pay(members, "Umid", 1_000_000, date(2026, 10, 2))
    r = admin_api.get(f"{URL}owed/", {"worker": " umid "})
    assert r.status_code == 200, r.data
    assert Decimal(r.data["total"]) == 4_000_000
    assert [(s["number"], Decimal(s["left"])) for s in r.data["sheets"]] == [
        (sep["number"], 2_000_000),
        (octo["number"], 2_000_000),
    ]
    assert admin_api.get(f"{URL}owed/", {"worker": "Boshqa"}).data["sheets"] == []
    assert api("accounting.view_operation").get(f"{URL}owed/", {"worker": "Umid"}).status_code == 403


def test_the_bot_shows_the_boss_what_is_owed(bot_client, admin_api, people, members, orders):
    import json
    from pathlib import Path

    approved(admin_api, people[2], "oddiy", month="2026-10", fixed="2000000")
    pay(members, "Umid", 500_000, date(2026, 11, 2))
    r = bot_client.get("finance/salary-owed/?worker=Umid", actor=100)  # the boss
    assert r.status_code == 200, r.data
    assert Decimal(r.data["total"]) == 1_500_000 and len(r.data["sheets"]) == 1
    fixture = Path(__file__).resolve().parents[3] / "docs" / "bot_contract" / "misc.salary_owed_response.json"
    if fixture.exists():  # the contract dir is mounted only in some runs
        want = json.loads(fixture.read_text(encoding="utf-8"))
        assert set(r.data) == set(want) and set(r.data["sheets"][0]) == set(want["sheets"][0])
    assert bot_client.get("finance/salary-owed/?worker=Umid", actor=200).status_code == 403


def test_draft_and_submitted_sheets_have_no_payment_block(admin_api, people):
    r = admin_api.post(URL, {"worker": people[2].pk, "kind": "oddiy", "month": "2026-10"}, format="json")
    assert r.data["payment"] is None and r.data["costs"] == []
    assert admin_api.get(URL).data["results"][0]["pay"] is None
