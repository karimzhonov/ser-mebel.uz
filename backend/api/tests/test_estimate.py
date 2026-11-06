"""The lead's approximate price (owner's rule): the operator, the zamerchi and the
manager add it to tell the client; not needed -> delete; needed -> «Bajarildi» gives it
to the chosen manager to finish (no new price)."""

import pytest
from rest_framework.test import APIClient

from api.tests.test_offer_stage2 import (  # noqa: F401 - fixtures + helpers
    ali,
    clock,
    lead,
    operator,
    price_manager,
    upload_file,
)
from metering import services as M
from metering.models import Metering
from metering.price import services as PS
from metering.price.models import Price

pytestmark = pytest.mark.django_db


def client_of(user):
    c = APIClient()
    c.force_authenticate(user)
    return c


def test_operator_adds_edits_and_deletes_the_leads_estimate(operator):
    inv = lead(operator)
    op = client_of(operator)  # no price rights at all
    assert not operator.has_perm("price.change_price")
    r = op.post(f"/api/v1/invoices/{inv.pk}/estimate/")
    assert r.status_code == 201, r.data
    pid = r.data["id"]
    p = Price.objects.get(pk=pid)
    assert p.stage == "estimate" and p.invoice_id == inv.pk and p.user_id is None
    assert op.post(f"/api/v1/invoices/{inv.pk}/estimate/").status_code == 400  # one per lead
    d = op.get(f"/api/v1/prices/{pid}/")
    assert d.status_code == 200 and d.data["actions"]["edit"] and d.data["actions"]["delete"]
    assert op.patch(f"/api/v1/prices/{pid}/", {"variant": "Standart"}, format="json").status_code == 200
    assert op.get("/api/v1/object-types/").status_code == 200  # the catalog to calculate
    # nothing else of «Narx hisoblash»
    assert op.get("/api/v1/prices/").status_code == 403
    other = Price.objects.create(desc="boshqa", stage="work")
    assert op.get(f"/api/v1/prices/{other.pk}/").status_code == 403
    assert op.post(f"/api/v1/prices/{pid}/done/").status_code in (400, 403)
    lead_row = op.get(f"/api/v1/invoices/{inv.pk}/").data["estimate"]
    assert lead_row["id"] == pid and lead_row["stage"] == "estimate"
    assert op.delete(f"/api/v1/prices/{pid}/").status_code == 204
    assert not Price.objects.filter(pk=pid).exists()
    assert op.get(f"/api/v1/invoices/{inv.pk}/").data["estimate"] is None


def test_bajarildi_gives_the_estimate_to_the_chosen_manager(
    operator, ali, make_staff, bot_events
):
    mgr = price_manager(make_staff, name="Menejer", telegram_id=9200)
    inv = lead(operator)
    est = PS.create_estimate(invoice=inv, by=operator)
    m = M.create_metering(
        client=inv.client, date_time=M._now(), invoice=inv, author=operator, measurer=ali
    )
    est.refresh_from_db()
    assert est.metering_id == m.pk  # it goes on with the lead
    # the zamerchi sees it as the zamer's price and may edit it before finishing
    assert client_of(ali).get(f"/api/v1/prices/{est.pk}/").status_code == 200
    M.mark_metering_measured(m, by=ali)
    upload_file(m)
    bot_events.clear()
    M.finish_metering(m, by=ali, note="O'lchandi", next_step="price", manager=mgr)
    assert Price.objects.filter(metering=m).count() == 1  # no new price
    est.refresh_from_db()
    assert est.stage == "work" and est.user_id == mgr.pk and est.due_at is not None
    ev = bot_events.one("offer.assigned")
    assert ev["to"] == [9200] and ev["task"]["id"] == est.pk
    # now it is the manager's task: only edited, never deleted from the lead
    with pytest.raises(Exception):
        PS.delete_estimate(est, by=operator)
    assert client_of(operator).delete(f"/api/v1/prices/{est.pk}/").status_code in (403, 405)


def test_zamerchi_adds_an_estimate_from_the_zamer(operator, ali):
    inv = lead(operator)
    m = M.create_metering(
        client=inv.client, date_time=M._now(), invoice=inv, author=operator, measurer=ali
    )
    r = client_of(ali).post(f"/api/v1/meterings/{m.pk}/estimate/")
    assert r.status_code == 201, r.data
    p = Price.objects.get(pk=r.data["id"])
    assert p.metering_id == m.pk and p.invoice_id == inv.pk and p.stage == "estimate"
    Metering.objects.filter(pk=m.pk).update(status="done")
    Price.objects.filter(pk=p.pk).delete()
    assert client_of(ali).post(f"/api/v1/meterings/{m.pk}/estimate/").status_code == 400


def test_only_for_that_price(operator, ali, make_staff):
    """Another zamerchi does not reach ali's zamer's estimate; a read-only viewer adds none."""
    inv = lead(operator)
    m = M.create_metering(
        client=inv.client, date_time=M._now(), invoice=inv, author=operator, measurer=ali
    )
    est = PS.create_estimate(metering=m, by=ali)
    other = make_staff("oauth.user_metering", "metering.view_metering", name="Boshqa")
    assert client_of(other).get(f"/api/v1/prices/{est.pk}/").status_code in (403, 404)
    assert client_of(other).delete(f"/api/v1/prices/{est.pk}/").status_code in (403, 404)
    viewer = make_staff("call_center.view_invoice", "metering.view_metering")
    assert client_of(viewer).post(f"/api/v1/invoices/{inv.pk}/estimate/").status_code in (400, 403)


def test_cancelled_zamer_leaves_the_estimate_on_the_lead(operator, ali):
    inv = lead(operator)
    m = M.create_metering(
        client=inv.client, date_time=M._now(), invoice=inv, author=operator, measurer=ali
    )
    Metering.objects.filter(pk=m.pk).update(status="dont_need")
    est = PS.create_estimate(invoice=inv, by=operator)
    assert est.metering_id is None and est.invoice_id == inv.pk
    m2 = M.create_metering(
        client=inv.client, date_time=M._now(), invoice=inv, author=operator, measurer=ali
    )
    est.refresh_from_db()
    assert est.metering_id == m2.pk  # the re-booked zamer takes it
