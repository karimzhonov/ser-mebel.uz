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


def test_waiting_bonuses_ignore_the_period(admin_api):
    """Money still to collect stays on «Kutilmoqda» whatever period is picked."""
    OrderBonus.objects.create(order_ref="old", ready_date=date(2026, 9, 10))
    OrderBonus.objects.create(order_ref="done", ready_date=date(2026, 9, 10), status="done")
    october = "date_from=2026-10-01&date_to=2026-10-31"
    assert _refs(admin_api.get(f"/api/v1/finance/bonuses/?status=waiting&{october}")) == ["old"]
    assert _refs(admin_api.get(f"/api/v1/finance/bonuses/?status=done&{october}")) == []


def test_unpaid_lists_every_ready_order_with_rest(admin_api, order_factory):
    """«Kutilmoqda» = Готов orders whose rest is not collected, bonus tracked or not."""
    from djmoney.money import Money

    from order.constants import OrderStatus
    from order.models import Order

    def ready(price, paid=None):
        o = order_factory(price=Money(price, "USD"))
        fields = {"status": OrderStatus.DONE}
        if paid is not None:
            fields["lost_money"] = Money(paid, "USD")
        Order.objects.filter(pk=o.pk).update(**fields)
        return str(o.order_number)

    untracked = ready(1000, 400)  # Готов before FIN_BONUS_SINCE: no bonus row
    tracked = ready(500)
    OrderBonus.objects.create(order_ref=tracked, ready_date=date(2026, 9, 1), total=500)
    ready(300, 300)  # paid in full
    collected = ready(200, 0)
    OrderBonus.objects.create(order_ref=collected, ready_date=date(2026, 9, 1), status="done")
    in_work = order_factory(price=Money(900, "USD"))  # not Готов yet

    r = admin_api.get("/api/v1/finance/bonuses/unpaid/")
    assert r.status_code == 200, r.content
    rows = {x["order_ref"]: x for x in r.data["results"]}
    assert set(rows) == {untracked, tracked} and str(in_work.order_number) not in rows
    assert r.data["count"] == 2
    assert rows[untracked]["rest"] == "600.00" and rows[untracked]["bonus_id"] is None
    assert rows[tracked]["bonus_status"] == "waiting" and rows[tracked]["rest"] == "500.00"
    assert r.data["rest"] == {"USD": "1100.00"}
    assert admin_api.get("/api/v1/finance/bonuses/unpaid/?search=zzz").data["count"] == 0
