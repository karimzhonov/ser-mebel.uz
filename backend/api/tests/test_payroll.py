"""«Oylik varaqlari» (payroll/): the salary sheet on the site instead of Excel.

Every template's maths (ODDIY, SBORKA, OFIS, MENEJER, SOTUV/ZAMER), the accountant →
boss flow, the frozen approved sheet with its PDF in each worker's folder, and that
stage 1 never books money."""

from datetime import date
from decimal import Decimal

import pytest
from constance import config

from accounting import services as S
from accounting.models import ManualOrder, Operation, OrderBonus, Worker, WorkerFile
from payroll.models import SalarySheet

pytestmark = pytest.mark.django_db

URL = "/api/v1/finance/salary-sheets/"
FILL = ("payroll.view_salarysheet", "payroll.add_salarysheet", "payroll.change_salarysheet")
APPROVE = ("payroll.view_salarysheet", "payroll.approve_salarysheet")


@pytest.fixture(autouse=True)
def _rate(db):
    config.FIN_USD_RATE = 12000.0


@pytest.fixture
def orders(db):
    for ref, client in [("370", "Ulug'bek"), ("378", "Akbar"), ("SM-001", "Moxir")]:
        ManualOrder.objects.create(ref=ref, client=client, price=1)
    return ["370", "378", "SM-001"]


@pytest.fixture
def people(db):
    d = Worker.objects.create(group="Sborka", name="Dilmurod", position="Usta")
    j = Worker.objects.create(group="Sborka", name="Jamshid", position="Usta")
    o = Worker.objects.create(group="Ofis", name="Umid", position="Menejer")
    return d, j, o


def advance(members, name, amount, on):
    return S.create_operation(
        member=members[0],
        kind="expense",
        amount=amount,
        category_code="oylik",
        worker=name,
        pay_type="Avans",
        on_date=on,
        actor_admin=True,
    )


def new(client, worker, kind, month="2026-10"):
    r = client.post(URL, {"worker": worker.pk, "kind": kind, "month": month}, format="json")
    assert r.status_code == 201, r.data
    return r.data


def patch(client, sheet, **body):
    return client.patch(f"{URL}{sheet['id']}/", body, format="json")


def amounts(t):
    return {x["label"]: Decimal(x["amount"]) for x in t["earned"] + t["minus"]}


# ---------------------------------------------------------------- the maths
def test_oddiy_fixed_minus_days_fine_and_advances(admin_api, people, members):
    umid = people[2]
    advance(members, "umid", 1_000_000, date(2026, 10, 10))
    advance(members, "Boshqa", 777, date(2026, 10, 10))  # someone else's advance
    s = new(admin_api, umid, "oddiy")
    assert s["period_start"] == "2026-10-01" and s["period_end"] == "2026-10-31"
    r = patch(
        admin_api, s, fixed="5000000", absent_days=2, absent_rate="100000", late_days=3, late_rate="20000"
    )
    assert r.status_code == 200, r.data
    t = r.data["totals"]
    assert Decimal(t["earned_total"]) == 5_000_000
    assert Decimal(t["minus_total"]) == 260_000
    assert Decimal(t["advances_total"]) == 1_000_000
    assert Decimal(t["rest"]) == 3_740_000
    assert len(r.data["advances"]) == 1


def test_sborka_jobs_by_order_id_shares_partner_advances_and_car_apart(
    admin_api, people, members, orders
):
    dil, jam, _ = people
    advance(members, "Dilmurod", 2_000_000, date(2026, 10, 3))
    advance(members, "Jamshid", 500_000, date(2026, 10, 4))
    s = new(admin_api, dil, "sborka")
    r = patch(
        admin_api,
        s,
        members=[{"worker": dil.pk, "share": "60"}, {"worker": jam.pk, "share": "40"}],
        lines=[
            {"section": "job", "order_ref": "370", "amount": "15942500"},
            {"section": "job", "order_ref": "#378", "amount": "25854650"},
            {"section": "car", "title": "Oktabr", "amount": "800000"},
        ],
    )
    assert r.status_code == 200, r.data
    d = r.data
    jobs = [x for x in d["lines"] if x["section"] == "job"]
    assert [(x["order_ref"], x["title"]) for x in jobs] == [("370", "Ulug'bek"), ("378", "Akbar")]
    t = d["totals"]
    assert Decimal(t["earned_total"]) == Decimal("41797150")
    assert Decimal(t["advances_total"]) == 2_500_000  # both partners' advances
    assert Decimal(t["rest"]) == Decimal("39297150")  # the car money is not in the rest
    assert Decimal(t["car_total"]) == 800_000
    m = {x["name"]: x for x in d["members"]}
    assert m["Dilmurod"]["share"] == "60" and Decimal(m["Dilmurod"]["amount"]) == Decimal("25078290")
    assert Decimal(m["Dilmurod"]["rest"]) == Decimal("23078290")
    assert Decimal(m["Jamshid"]["amount"]) == Decimal("16718860")
    assert Decimal(m["Jamshid"]["rest"]) == Decimal("16218860")


def test_menejer_bonus_is_percent_of_the_order_in_dollars_not_the_order(admin_api, people, orders):
    s = new(admin_api, people[2], "menejer")
    r = patch(
        admin_api,
        s,
        fixed="5000000",
        bonus_percent="3",
        bonus2_percent="1.8",
        lines=[
            {"section": "taken", "order_ref": "370", "amount": "1000"},
            {"section": "delivered", "order_ref": "378", "amount": "2000"},
        ],
    )
    assert r.status_code == 200, r.data
    e = amounts(r.data["totals"])
    assert e["Olingan zakazlar bonusi"] == 360_000  # 1000 $ × 3 % × 12 000
    assert e["Topshirilgan zakazlar bonusi"] == 432_000  # 2000 $ × 1.8 % × 12 000
    assert Decimal(r.data["totals"]["rest"]) == 5_792_000
    assert r.data["bonus_percent"] == "3"


def test_preview_shows_client_order_sum_and_live_totals_without_saving(admin_api, people, orders):
    ManualOrder.objects.filter(ref="370").update(price=24_000_000)
    s = new(admin_api, people[2], "menejer")
    body = {
        "fixed": "5000000",
        "bonus_percent": "3",
        "lines": [
            {"section": "taken", "order_ref": "370", "amount": "1000"},
            {"section": "taken", "order_ref": "999", "amount": "500"},  # no such order
            {"section": "taken", "order_ref": "", "amount": ""},  # half-typed row
        ],
    }
    r = admin_api.post(f"{URL}{s['id']}/preview/", body, format="json")
    assert r.status_code == 200, r.data
    rows = r.data["lines"]
    assert rows[0]["found"] is True
    assert rows[0]["order"]["client"] == "Ulug'bek"
    assert Decimal(rows[0]["order"]["total_usd"]) == 2000  # 24 mln so'm / 12 000
    assert Decimal(rows[0]["calc"]["value"]) == 360_000
    assert rows[1]["found"] is False and rows[1]["order"] is None
    assert Decimal(rows[2]["calc"]["value"]) == 0
    assert Decimal(r.data["totals"]["earned_total"]) == 5_000_000 + 360_000 + 180_000
    # nothing was written
    fresh = admin_api.get(f"{URL}{s['id']}/").data
    assert fresh["lines"] == [] and Decimal(fresh["totals"]["earned_total"]) == 0


def test_preview_needs_the_fill_permission(api, people, orders):
    s = SalarySheet.objects.create(
        number=1,
        kind="oddiy",
        worker=people[2],
        month=date(2026, 10, 1),
        period_start=date(2026, 10, 1),
        period_end=date(2026, 10, 31),
        usd_rate=12000,
    )
    c = api("payroll.view_salarysheet")
    assert c.post(f"{URL}{s.pk}/preview/", {}, format="json").status_code == 403


def _done_bonus(ref, receiver, **kw):
    data = dict(
        order_ref=ref,
        client="Ulug'bek",
        total=Decimal(1000),
        currency="USD",
        ready_date=date(2026, 10, 1),
        paid_date=date(2026, 10, 3),
        status="done",
        days=2,
        percent=Decimal("0.5"),
        bonus=Decimal(59_000),  # fixed in «Bonuslar» at that day's rate, not the sheet's
        receiver=receiver,
    )
    data.update(kw)
    return OrderBonus.objects.create(**data)


def test_zamer_takes_collect_bonus_from_bonuslar_once(admin_api, people, orders):
    umid, jam = people[2], people[1]
    mine = _done_bonus("370", "Umid")
    _done_bonus("378", "Boshqa odam")  # someone else's
    _done_bonus("SM-001", "Umid", paid_date=date(2026, 11, 5))  # next period
    s = new(admin_api, umid, "zamer")
    rows = [x for x in s["lines"] if x["section"] == "collect"]
    assert [(x["order_ref"], x["order_bonus"], Decimal(x["value"])) for x in rows] == [
        ("370", mine.pk, 59_000)
    ]
    assert amounts(s["totals"])["Pul yechish bonusi"] == 59_000

    # saving keeps the link and the «Bonuslar» numbers, whatever the row says
    r = patch(
        admin_api,
        s,
        lines=[{"section": "collect", "order_bonus": mine.pk, "amount": "1", "on_date": "2026-01-01"}],
    )
    assert r.status_code == 200, r.data
    row = r.data["lines"][0]
    assert (row["on_date"], row["paid_on"], row["days"], Decimal(row["value"])) == (
        "2026-10-01",
        "2026-10-03",
        2,
        59_000,
    )

    found = admin_api.get(f"{URL}{s['id']}/order-bonuses/").data
    assert found["matched"] is True and [x["order_ref"] for x in found["rows"]] == ["370"]

    # the same bonus on another sheet is refused
    other = new(admin_api, jam, "zamer")
    r = patch(admin_api, other, lines=[{"section": "collect", "order_bonus": mine.pk}])
    assert r.status_code == 400 and "ikki marta" in str(r.data)

    # a hand-typed row for a tracked order is flagged
    r = patch(
        admin_api,
        other,
        lines=[
            {"section": "collect", "order_ref": "378", "on_date": "2026-10-01", "paid_on": "2026-10-02", "currency": "UZS", "amount": "100"}
        ],
    )
    assert r.status_code == 200 and any("Bonuslar" in w for w in r.data["warnings"])


def test_zamer_collect_bonus_by_days_and_instagram_tiers(admin_api, people, orders):
    s = new(admin_api, people[2], "zamer")
    r = patch(
        admin_api,
        s,
        instagram_count=25,
        lines=[
            # 2 days → 0.5 %; 1000 $ × 12 000 × 0.5 % = 60 000
            {"section": "collect", "order_ref": "370", "on_date": "2026-10-01", "paid_on": "2026-10-03", "currency": "USD", "amount": "1000"},
            # 10 days → 0.3 % of 10 000 000 so'm = 30 000
            {"section": "collect", "order_ref": "378", "on_date": "2026-10-01", "paid_on": "2026-10-11", "currency": "UZS", "amount": "10000000"},
            # 40 days → 0
            {"section": "collect", "order_ref": "SM-001", "on_date": "2026-09-01", "paid_on": "2026-10-11", "currency": "UZS", "amount": "5000000"},
        ],
    )
    assert r.status_code == 200, r.data
    rows = [x for x in r.data["lines"] if x["section"] == "collect"]
    assert [(x["days"], x["percent"], Decimal(x["value"])) for x in rows] == [
        (2, "0.5", 60_000),
        (10, "0.3", 30_000),
        (40, "0", 0),
    ]
    e = amounts(r.data["totals"])
    assert e["Pul yechish bonusi"] == 90_000
    assert e["Instagram bonusi"] == 600_000  # 25 stories → 50 $


def test_ofis_deductions_are_not_advances(admin_api, people, members, orders):
    advance(members, "Umid", 300_000, date(2026, 10, 2))
    s = new(admin_api, people[2], "ofis")
    r = patch(
        admin_api,
        s,
        fixed="4000000",
        bonus_percent="1.2",
        lines=[
            {"section": "taken", "order_ref": "370", "amount": "1000"},
            {"section": "deduction", "title": "Beydjik", "on_date": "2026-10-05", "amount": "50000"},
            {"section": "deduction", "title": "Dollar", "currency": "USD", "rate": "11000", "amount": "10"},
        ],
    )
    assert r.status_code == 200, r.data
    t = r.data["totals"]
    assert amounts(t)["Ushlanmalar"] == 160_000
    assert Decimal(t["advances_total"]) == 300_000
    assert Decimal(t["rest"]) == 4_000_000 + 144_000 - 160_000 - 300_000


# ---------------------------------------------------------------- validation
@pytest.mark.parametrize(
    "body, field",
    [
        ({"lines": [{"section": "job", "order_ref": "99999", "amount": "10"}]}, "lines"),
        ({"lines": [{"section": "job", "order_ref": "", "amount": "10"}]}, "lines"),
        ({"lines": [{"section": "job", "order_ref": "370", "amount": "0"}]}, "lines"),
        ({"lines": [{"section": "taken", "order_ref": "370", "amount": "10"}]}, "lines"),
        ({"members": [{"worker": 0, "share": "100"}]}, "members"),
        ({"period_start": "2026-11-01", "period_end": "2026-10-01"}, "period_start"),
    ],
)
def test_bad_input_is_refused(admin_api, people, orders, body, field):
    s = new(admin_api, people[0], "sborka")
    r = patch(admin_api, s, **body)
    assert r.status_code == 400, r.data


def test_shares_must_make_100_and_the_owner_comes_first(admin_api, people, orders):
    dil, jam, _ = people
    s = new(admin_api, dil, "sborka")
    bad = patch(admin_api, s, members=[{"worker": dil.pk, "share": "60"}, {"worker": jam.pk, "share": "30"}])
    assert bad.status_code == 400
    swapped = patch(admin_api, s, members=[{"worker": jam.pk, "share": "50"}, {"worker": dil.pk, "share": "50"}])
    assert swapped.status_code == 400


def test_one_sheet_per_worker_and_month_and_no_future_month(admin_api, people):
    new(admin_api, people[2], "oddiy")
    again = admin_api.post(URL, {"worker": people[2].pk, "kind": "oddiy", "month": "2026-10"}, format="json")
    assert again.status_code == 400
    future = admin_api.post(URL, {"worker": people[2].pk, "kind": "oddiy", "month": "2099-01"}, format="json")
    assert future.status_code == 400


def test_new_sheet_copies_the_previous_one(admin_api, people, orders):
    dil, jam, _ = people
    s = new(admin_api, dil, "sborka", month="2026-09")
    patch(admin_api, s, members=[{"worker": dil.pk, "share": "70"}, {"worker": jam.pk, "share": "30"}])
    r = admin_api.post(URL, {"worker": dil.pk, "month": "2026-10"}, format="json")
    assert r.status_code == 201, r.data
    assert r.data["kind"] == "sborka"
    assert [(m["name"], m["share"]) for m in r.data["members"]] == [("Dilmurod", "70"), ("Jamshid", "30")]


def test_duplicate_order_id_is_a_warning_not_an_error(admin_api, people, orders):
    dil, jam, _ = people
    a = new(admin_api, dil, "sborka")
    patch(admin_api, a, lines=[{"section": "job", "order_ref": "370", "amount": "100"}])
    b = new(admin_api, jam, "sborka")
    r = patch(admin_api, b, lines=[{"section": "job", "order_ref": "370", "amount": "100"}] * 2)
    assert r.status_code == 200
    text = " ".join(r.data["warnings"])
    assert "2 marta" in text and f"№{a['number']}" in text


# ---------------------------------------------------------------- the flow
def test_accountant_fills_and_sends_boss_approves_pdf_lands_in_every_folder(
    api, people, members, orders
):
    dil, jam, _ = people
    acc = api(*FILL, "payroll.delete_salarysheet")
    boss = api(*APPROVE, name="Rahbar")
    advance(members, "Dilmurod", 1_000_000, date(2026, 10, 3))
    ops_before = Operation.objects.count()

    s = new(acc, dil, "sborka")
    assert s["can"]["edit"] and not s["can"]["approve"]
    patch(
        acc,
        s,
        members=[{"worker": dil.pk, "share": "50"}, {"worker": jam.pk, "share": "50"}],
        lines=[{"section": "job", "order_ref": "370", "amount": "4000000"}],
    )
    assert acc.post(f"{URL}{s['id']}/approve/").status_code == 403
    r = acc.post(f"{URL}{s['id']}/submit/")
    assert r.status_code == 200 and r.data["status"] == "submitted"
    assert patch(acc, s, note="x").status_code == 400  # locked once sent

    r = boss.post(f"{URL}{s['id']}/approve/")
    assert r.status_code == 200, r.data
    assert r.data["status"] == "approved" and r.data["version"] == 1
    files = WorkerFile.objects.filter(kind="salary", month=date(2026, 10, 1))
    assert {f.worker_id for f in files} == {dil.pk, jam.pk}
    f = files.first()
    assert bytes(f.data).startswith(b"%PDF") and f.content_type == "application/pdf"

    # frozen: a later advance does not change the approved sheet
    advance(members, "Dilmurod", 999_000, date(2026, 10, 20))
    again = acc.get(f"{URL}{s['id']}/")
    assert Decimal(again.data["totals"]["advances_total"]) == 1_000_000
    # stage 1 books no money
    assert Operation.objects.count() == ops_before + 1  # only the advance above
    assert acc.delete(f"{URL}{s['id']}/").status_code == 400


def test_returning_an_approved_sheet_needs_the_boss_and_a_reason(api, people, orders):
    acc = api(*FILL)
    boss = api(*APPROVE)
    s = new(acc, people[2], "oddiy")
    patch(acc, s, fixed="3000000")
    assert boss.post(f"{URL}{s['id']}/approve/").status_code == 200
    assert acc.post(f"{URL}{s['id']}/return/", {"reason": "x"}).status_code == 403
    assert boss.post(f"{URL}{s['id']}/return/", {}).status_code == 400
    r = boss.post(f"{URL}{s['id']}/return/", {"reason": "Fiksa xato"})
    assert r.status_code == 200 and r.data["status"] == "draft"
    assert r.data["returned_note"] == "Fiksa xato"
    patch(acc, s, fixed="3500000")
    r = boss.post(f"{URL}{s['id']}/approve/")
    assert r.data["version"] == 2
    names = list(WorkerFile.objects.filter(worker=people[2]).values_list("name", flat=True))
    assert len(names) == 2 and any(n.endswith("_v2.pdf") for n in names)


def test_view_only_user_cannot_create_and_no_perm_sees_nothing(api, people):
    viewer = api("payroll.view_salarysheet")
    assert viewer.post(URL, {"worker": people[2].pk, "kind": "oddiy"}, format="json").status_code == 403
    stranger = api()
    assert stranger.get(URL).status_code == 403


def test_list_filters_and_pdf(admin_api, people, orders):
    s = new(admin_api, people[2], "oddiy")
    patch(admin_api, s, fixed="1000000")
    r = admin_api.get(URL, {"status": "draft", "month": "2026-10"})
    assert r.status_code == 200 and r.data["count"] == 1
    assert r.data["results"][0]["rest"] == 1_000_000.0
    assert admin_api.get(URL, {"status": "approved"}).data["count"] == 0
    pdf = admin_api.get(f"{URL}{s['id']}/pdf/")
    assert pdf.status_code == 200 and pdf["Content-Type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
    opts = admin_api.get(f"{URL}options/")
    assert opts.status_code == 200 and {k["value"] for k in opts.data["kinds"]} >= {"sborka", "zamer"}
    assert SalarySheet.objects.count() == 1
