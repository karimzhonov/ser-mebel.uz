"""«👷 Ishchi kartasi»: GET /api/v1/finance/worker-card/."""

from datetime import date

import pytest

from accounting import services as S
from accounting.models import Worker

pytestmark = pytest.mark.django_db

URL = "/api/v1/finance/worker-card/"


def _pay(member, amount, worker, pay_type="Avans", day=date(2026, 10, 5), **kw):
    return S.create_operation(
        member=member,
        kind="expense",
        amount=amount,
        category_code="oylik",
        worker=worker,
        pay_type=pay_type,
        on_date=day,
        internal=True,
        **kw,
    )


@pytest.fixture
def paid(members):
    boss, ali, _ = members
    Worker.objects.all().delete()  # the seeded catalog
    Worker.objects.create(group="1-komanda", name="Dilmurod", position="bosh usta")
    Worker.objects.create(group="Zavod", name="Jumaka", position="Servis")
    _pay(boss, 1_000_000, "Dilmurod", "Avans", date(2026, 10, 3))
    _pay(ali, 3_000_000, " dilmurod ", "Oylik", date(2026, 10, 20))
    _pay(boss, 500_000, "Dilmurod", "Avans", date(2026, 9, 1))  # outside the period
    _pay(boss, 200_000, "Shogird", "Avans", date(2026, 10, 7))  # not in the catalog
    deleted = _pay(boss, 9_000_000, "Dilmurod", "Oylik", date(2026, 10, 9))
    deleted.is_deleted = True
    deleted.save()
    return boss, ali


def test_card_sums_advance_salary_and_givers(admin_api, paid):
    r = admin_api.get(
        URL, {"worker": "Dilmurod", "date_from": "2026-10-01", "date_to": "2026-10-31"}
    )
    assert r.status_code == 200, r.content
    c = r.data["card"]
    assert (c["advance"], c["salary"], c["total"], c["count"]) == (
        1_000_000,
        3_000_000,
        4_000_000,
        2,
    )
    assert c["all_time"] == 4_500_000 and c["last_date"] == date(2026, 10, 20)
    assert (c["group"], c["position"], c["in_catalog"]) == ("1-komanda", "bosh usta", True)
    assert [g["name"] for g in c["by_giver"]] == ["Ali", "Rahbar"]
    assert [x["date"] for x in c["rows"]] == [date(2026, 10, 20), date(2026, 10, 3)]


def test_list_has_catalog_and_hand_written_workers(admin_api, paid):
    r = admin_api.get(URL, {"date_from": "2026-10-01", "date_to": "2026-10-31"})
    by = {w["name"]: w for w in r.data["workers"]}
    assert r.data["card"] is None
    assert by["Dilmurod"]["total"] == 4_000_000 and by["Dilmurod"]["count"] == 2
    assert by["Jumaka"]["total"] == 0 and by["Jumaka"]["in_catalog"]
    assert by["Shogird"]["in_catalog"] is False and by["Shogird"]["total"] == 200_000


def test_staff_without_view_all_is_refused(api, paid):
    client = api("accounting.view_operation")
    assert client.get(URL).status_code == 403


# ------------------------------------------------ the boss's own salary («Uy uchun»)
def test_home_pay_type_only_on_the_boss_salary(admin_api, members):
    from core.exceptions import ServiceError

    boss = members[0]
    Worker.objects.all().delete()
    Worker.objects.create(group="Ofis", name="Mirmuxammad", position="rahbar", is_boss=True)
    Worker.objects.create(group="Zavod", name="Jumaka", position="")
    _pay(boss, 2_000_000, "Mirmuxammad", "Uy uchun", date(2026, 10, 4))
    _pay(boss, 5_000_000, "Mirmuxammad", "Oylik", date(2026, 10, 25))
    with pytest.raises(ServiceError):
        _pay(boss, 100_000, "Jumaka", "Uy uchun")
    with pytest.raises(ServiceError):
        _pay(boss, 100_000, "Jumaka", "Bonus")

    # the site API: same rule
    url = "/api/v1/finance/operations/"
    body = {"member": boss.id, "kind": "expense", "amount": "1000", "category_code": "oylik"}
    r = admin_api.post(url, {**body, "worker": "Jumaka", "pay_type": "Uy uchun"}, format="json")
    assert r.status_code == 400
    boss_home = {**body, "worker": "Mirmuxammad", "pay_type": "Uy uchun"}
    r = admin_api.post(url, boss_home, format="json")
    assert r.status_code == 201, r.content

    r = admin_api.get(
        URL, {"worker": "Mirmuxammad", "date_from": "2026-10-01", "date_to": "2026-10-31"}
    )
    c = r.data["card"]
    assert c["is_boss"] is True
    assert (c["home"], c["salary"], c["advance"], c["other"]) == (2_000_000, 5_000_000, 0, 0)
    assert {x["pay_type"] for x in c["rows"]} == {"Uy uchun", "Oylik"}


def test_personal_categories_are_retired(members):
    from accounting.models import FinanceCategory
    from core.exceptions import ServiceError

    boss = members[0]
    assert not FinanceCategory.objects.filter(code__in=["uy", "rahbarga"], is_active=True).exists()
    for code in ("uy", "rahbarga"):
        with pytest.raises(ServiceError):
            S.create_operation(
                member=boss, kind="expense", amount=1000, category_code=code, actor_admin=True
            )
    assert "uy" not in {c.code for c in S.categories("expense")}


def test_bot_worker_dto_carries_is_boss(bot_client, members):
    Worker.objects.create(group="Ofis", name="Mirmuxammad", position="rahbar", is_boss=True)
    r = bot_client.get("finance/workers/", actor=members[0].telegram_id)
    assert r.status_code == 200, r.content
    row = next(w for w in r.data if w["name"] == "Mirmuxammad")
    assert row["is_boss"] is True
