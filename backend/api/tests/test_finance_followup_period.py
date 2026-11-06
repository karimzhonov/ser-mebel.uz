"""«Готов va bonuslar»: every tab is filtered by a period (?date_from / ?date_to)."""

from datetime import date

from accounting.models import OrderBonus, SiteEntryTask, WarrantyLetter


def _refs(resp):
    assert resp.status_code == 200, resp.content
    return sorted(r["order_ref"] for r in resp.data["results"])


def test_bonuses_warranty_and_site_entry_by_period(admin_api):
    OrderBonus.objects.create(order_ref="1", ready_date=date(2026, 9, 10))
    OrderBonus.objects.create(order_ref="2", ready_date=date(2026, 10, 5))
    WarrantyLetter.objects.create(order_ref="1", ready_date=date(2026, 9, 10))
    WarrantyLetter.objects.create(order_ref="2", ready_date=date(2026, 10, 5))
    SiteEntryTask.objects.create(code="a", order_ref="1", date=date(2026, 9, 10))
    SiteEntryTask.objects.create(code="b", order_ref="2", date=date(2026, 10, 5))

    october = "date_from=2026-10-01&date_to=2026-10-31"
    assert _refs(admin_api.get(f"/api/v1/finance/bonuses/?status=&{october}")) == ["2"]
    assert _refs(admin_api.get("/api/v1/finance/bonuses/?status=")) == ["1", "2"]
    assert _refs(admin_api.get(f"/api/v1/finance/warranty/?{october}")) == ["2"]
    assert _refs(admin_api.get("/api/v1/finance/site-entry/?date_to=2026-09-30")) == ["1"]
    bad = admin_api.get("/api/v1/finance/bonuses/?date_from=2026-10-31&date_to=2026-10-01")
    assert bad.status_code == 400
