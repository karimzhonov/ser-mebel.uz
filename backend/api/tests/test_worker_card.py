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
