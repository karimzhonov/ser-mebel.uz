"""Location feature: the cases the main test_location.py leaves open (inheritance through the
panel API, fill-down limits, data migrations, history users, candidates ordering/gating,
dashboard cards)."""

import importlib
from datetime import timedelta
from decimal import Decimal

import pytest

from api.tests.test_location import (
    INV_PERMS,
    MET_PERMS,
    NOW,
    P2,
    YA,
    P,
    _order_chain,
    _order_payload,
    mk,
    mk_metering,
    seller,  # noqa: F401  (fixture)
)
from call_center import services as CC
from call_center.constants import SolutionChoice
from call_center.models import Invoice
from core.exceptions import ServiceError
from metering.models import Metering
from metering.services import create_metering, set_metering_location
from order.models import Order
from order.services import set_order_location

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("default_measurer")]


# ------------------------------------------------------------ inheritance via the panel API
def test_panel_metering_create_inherits_the_invoice_location(admin_api):
    r = admin_api.post(
        "/api/v1/invoices/",
        {
            "fio": "Ali",
            "phone": "+998901113344",
            "source": "phone",
            "address": "Chilonzor 5",
            "location": "41.311081, 69.279737",
        },
        format="json",
    )
    assert r.status_code == 201, r.content
    r = admin_api.post(
        "/api/v1/meterings/",
        {
            "client_phone": "+998901113344",
            "date_time": "2026-10-25T10:00:00",
            "invoice": r.data["id"],
        },
        format="json",
    )
    assert r.status_code == 201, r.content
    assert (r.data["lat"], r.data["lon"], r.data["address"]) == (
        "41.311081",
        "69.279737",
        "Chilonzor 5",
    )
    assert r.data["map_url"] == YA


def test_panel_metering_own_location_beats_the_invoice(admin_api):
    inv = admin_api.post(
        "/api/v1/invoices/",
        {
            "fio": "Ali",
            "phone": "+998901113355",
            "source": "phone",
            "location": "41.311081, 69.279737",
        },
        format="json",
    ).data["id"]
    r = admin_api.post(
        "/api/v1/meterings/",
        {
            "client_phone": "+998901113355",
            "date_time": "2026-10-25T10:00:00",
            "invoice": inv,
            "location": "40.5, 68.5",
        },
        format="json",
    )
    assert r.status_code == 201, r.content
    assert (r.data["lat"], r.data["lon"]) == ("40.500000", "68.500000")


def test_metering_without_invoice_or_location_stays_blank(seller):
    m = create_metering(client=mk(seller).client, date_time=NOW)
    assert m.lat is None and m.lon is None and not m.address_link


# ------------------------------------------------------------ fill-down limits
def test_fill_down_reaches_metering_and_order_only_where_blank(admin_api, seller):
    inv_id, mid, dtype = _order_chain(admin_api, address="Lead manzili")
    order = admin_api.post("/api/v1/orders/", _order_payload(mid, dtype), format="json")
    assert order.status_code == 201, order.content
    oid = order.data["id"]
    assert order.data["lat"] is None
    Order.objects.filter(pk=oid).update(address="Buyurtma manzili")
    inv = Invoice.objects.get(pk=inv_id)
    _, changed, filled = CC.set_invoice_location(inv, point=P, address="Yangi", by=seller)
    assert changed
    assert filled == [("metering", mid), ("order", oid)]
    m = Metering.objects.get(pk=mid)
    o = Order.objects.get(pk=oid)
    assert m.lat == P.lat and m.address == "Lead manzili"  # typed address kept
    assert o.lat == P.lat
    assert o.address == "Buyurtma manzili"  # never overwritten


def test_archived_metering_refuses_and_leaves_the_order_point_intact(admin_api, seller):
    _, mid, dtype = _order_chain(admin_api, address="A")
    r = admin_api.post(
        "/api/v1/orders/", _order_payload(mid, dtype, location="40.5, 68.5"), format="json"
    )
    assert r.status_code == 201, r.content
    o = Order.objects.get(pk=r.data["id"])
    # the metering is archived now (sold out), so the service refuses; the order point is intact
    with pytest.raises(ServiceError):
        set_metering_location(Metering.objects.get(pk=mid), point=P, by=seller)
    o.refresh_from_db()
    assert o.lat == P2.lat


def test_set_metering_location_without_an_order_fills_nothing(seller):
    m = mk_metering(mk(seller))
    _, changed, filled = set_metering_location(m, point=P, address="Manzil", by=seller)[:3]
    assert changed and filled == []


def test_same_point_again_is_idempotent_for_metering_and_order(admin_api, seller):
    inv = mk(seller)
    m = mk_metering(inv)
    assert set_metering_location(m, point=P, by=seller)[1] is True
    m.refresh_from_db()
    assert set_metering_location(m, point=P, by=seller)[1] is False


def test_set_order_location_idempotent_and_needs_address_or_point(admin_api, seller):
    _, mid, dtype = _order_chain(admin_api, address="A")
    oid = admin_api.post("/api/v1/orders/", _order_payload(mid, dtype), format="json").data["id"]
    o = Order.objects.get(pk=oid)
    assert set_order_location(o, point=P, by=seller)[1] is True
    o.refresh_from_db()
    assert set_order_location(o, point=P, by=seller)[1] is False
    Order.objects.filter(pk=oid).update(address="")
    o.refresh_from_db()
    with pytest.raises(ServiceError):
        set_order_location(o, point=None, by=seller)  # blank address and no point
    o.refresh_from_db()
    assert o.lat == P.lat  # the failed clear rolled back


# ------------------------------------------------------------ data migrations
def _mod(name):
    return importlib.import_module(name)


def test_metering_backfill_migration_function(seller):
    from django.apps import apps

    mod = _mod("metering.migrations.0013_backfill_location")
    inv = mk(seller)
    good = mk_metering(inv)
    short = mk_metering(mk(seller, "+998901112244"))
    junk = mk_metering(mk(seller, "+998901112255"))
    had = mk_metering(mk(seller, "+998901112266"), lat=P2.lat, lon=P2.lon)
    Metering.objects.filter(pk=good.pk).update(
        address_link="https://yandex.ru/maps/?pt=69.279737,41.311081"
    )
    Metering.objects.filter(pk=short.pk).update(address_link="https://maps.app.goo.gl/abc")
    Metering.objects.filter(pk=junk.pk).update(address_link="не ссылка")
    Metering.objects.filter(pk=had.pk).update(
        address_link="https://yandex.ru/maps/?pt=69.279737,41.311081"
    )
    mod.backfill(apps, None)
    for m in (good, short, junk, had):
        m.refresh_from_db()
    assert (good.lat, good.lon) == (Decimal("41.311081"), Decimal("69.279737"))
    assert short.lat is None and junk.lat is None
    assert had.lat == P2.lat  # an existing point is never replaced
    mod.backfill(apps, None)  # re-running changes nothing
    good.refresh_from_db()
    assert good.lat == Decimal("41.311081")


def test_order_backfill_migration_function(admin_api):
    from django.apps import apps

    mod = _mod("order.migrations.0025_backfill_location")
    ids = []
    for i, phone in enumerate(("+998901113001", "+998901113002", "+998901113003")):
        _, mid, dtype = _order_chain(admin_api, phone=phone, address=f"A{i}")
        ids.append(
            admin_api.post("/api/v1/orders/", _order_payload(mid, dtype), format="json").data["id"]
        )
    good, short, junk = ids
    Order.objects.filter(pk=good).update(
        address_link="https://www.google.com/maps/place/X/data=!3d41.311081!4d69.279737"
    )
    Order.objects.filter(pk=short).update(address_link="https://yandex.uz/maps/-/CCUabc")
    Order.objects.filter(pk=junk).update(address_link="mazmuni yo'q")
    mod.backfill(apps, None)
    g, s, j = (Order.objects.get(pk=i) for i in ids)
    assert (g.lat, g.lon) == (Decimal("41.311081"), Decimal("69.279737"))
    assert s.lat is None and j.lat is None


# ------------------------------------------------------------ history user from a bot request
def test_bot_location_history_rows_get_the_acting_user(bot_client, seller, make_staff):
    staff = make_staff(*INV_PERMS, *MET_PERMS, name="Hist", telegram_id=4400)
    inv = mk(seller)
    m = mk_metering(inv)
    r = bot_client.post(
        "crm/locations/",
        actor=4400,
        data={"target": {"kind": "metering", "id": m.pk}, "lat": "41.3", "lon": "69.2"},
    )
    assert r.status_code == 200, r.content
    assert m.history.first().history_user_id == staff.pk
    r = bot_client.post(
        "crm/locations/",
        actor=4400,
        data={"target": {"kind": "invoice", "id": inv.pk}, "lat": "40.1", "lon": "68.1"},
    )
    assert r.status_code == 200, r.content
    assert Metering.objects.get(pk=m.pk).lat == Decimal("41.300000")  # not overwritten
    note = Invoice.objects.get(pk=inv.pk).notes.filter(kind="location").first()
    assert note.author_id == staff.pk and note.meta["via"] == "bot"


# ------------------------------------------------------------ candidates ordering / gating
def _items(r):
    return [(i["kind"], i["id"]) for i in r.data["items"]]


def test_candidates_own_invoices_newest_first_capped_at_five(bot_client, seller):
    made = []
    for i in range(7):
        inv = mk(seller, f"+99890111{3100 + i}")
        Invoice.objects.filter(pk=inv.pk).update(solution=SolutionChoice.given_location)
        made.append(inv.pk)
    r = bot_client.get("crm/locations/candidates/", actor=4001)
    assert [i for k, i in _items(r)] == sorted(made, reverse=True)[:5]


def test_candidates_metering_order_nopoint_first_then_date_nulls_last(bot_client, make_staff):
    make_staff(*MET_PERMS, telegram_id=4500)
    s = make_staff(*INV_PERMS, name="X", telegram_id=4501)
    late_pt = mk_metering(mk(s, "+998901113201"), lat=P.lat, lon=P.lon)
    soon_pt = create_metering(
        client=mk(s, "+998901113202").client, date_time=NOW, lat=P.lat, lon=P.lon
    )
    later_no = create_metering(
        client=mk(s, "+998901113203").client, date_time=NOW + timedelta(days=9)
    )
    sooner_no = create_metering(
        client=mk(s, "+998901113204").client, date_time=NOW + timedelta(days=2)
    )
    other_day = create_metering(client=mk(s, "+998901113205").client, date_time=NOW)
    Metering.objects.filter(pk=other_day.pk).update(status="other_day")
    done = create_metering(client=mk(s, "+998901113206").client, date_time=NOW)
    Metering.objects.filter(pk=done.pk).update(status="done")
    r = bot_client.get("crm/locations/candidates/", actor=4500)
    got = [i for _, i in _items(r)]
    assert got[:3] == [other_day.pk, sooner_no.pk, later_no.pk]  # no point, by date asc
    assert got[3:] == [soon_pt.pk, late_pt.pk]  # then those with a point, by date asc
    assert done.pk not in got
    assert all(k == "metering" for k, _ in _items(r))
    assert r.data["can_new_lead"] is False  # no add+view invoice


def test_candidates_gating_per_kind(bot_client, make_staff, seller):
    inv = mk(seller)
    Invoice.objects.filter(pk=inv.pk).update(
        solution=SolutionChoice.given_location,
        assigned_to=make_staff(
            "call_center.view_invoice", "call_center.change_invoice", telegram_id=4600
        ),
    )
    m = mk_metering(mk(seller, "+998901113301"))
    # invoice perms only: never meterings
    r = bot_client.get("crm/locations/candidates/", actor=4600)
    assert _items(r) == [("invoice", inv.pk)]
    # metering perms only: never invoices, even by phone
    make_staff(*MET_PERMS, telegram_id=4601)
    r = bot_client.get("crm/locations/candidates/?phone=%2B998901113301", actor=4601)
    assert _items(r) == [("metering", m.pk)]
    r = bot_client.get("crm/locations/candidates/?phone=%2B998901112233", actor=4601)
    assert r.data["items"] == []


# ------------------------------------------------------------ dashboard board cards
def test_board_cards_carry_map_url(admin_api, seller):
    inv = mk(seller, lat=P.lat, lon=P.lon)
    m = mk_metering(inv)
    r = admin_api.get("/api/v1/dashboard/boards/")
    assert r.status_code == 200
    boards = r.data["boards"] if isinstance(r.data, dict) else r.data
    cards = [
        c for b in boards if b["id"] == "meterings" for col in b["columns"] for c in col["cards"]
    ]
    card = next(c for c in cards if c["id"] == m.pk)
    assert (card["lat"], card["lon"], card["map_url"]) == ("41.311081", "69.279737", YA)


def test_overview_upcoming_without_a_point_falls_back_to_text_search(admin_api, seller):
    m = mk_metering(mk(seller), address="Chilonzor 5")
    Metering.objects.filter(pk=m.pk).update(address="Chilonzor 5")
    up = admin_api.get("/api/v1/dashboard/overview/").data["meterings"]["upcoming"]
    row = next(u for u in up if u["id"] == m.pk)
    assert row["lat"] is None and "text=Chilonzor%205" in row["map_url"]


def test_panel_same_point_keeps_link_and_missing_location_keeps_point(seller):
    inv = mk(seller)
    CC.set_invoice_location(
        inv, point=P, link="https://yandex.uz/maps/-/abc", address="A", by=seller
    )
    # re-saving the prefilled "lat, lon" (no link) keeps the pasted link
    CC.set_invoice_location(inv, point=P, link=None, address="B", by=seller)
    inv.refresh_from_db()
    assert inv.address_link == "https://yandex.uz/maps/-/abc" and inv.address == "B"
    # no location key: only the address changes, panel may clear it
    from core.geo import UNSET

    CC.set_invoice_location(inv, point=UNSET, link=UNSET, address="", by=seller)
    inv.refresh_from_db()
    assert inv.address == "" and inv.lat == P.lat
    assert inv.address_link == "https://yandex.uz/maps/-/abc"


def test_bot_duplicate_lead_gets_a_late_location(bot_client, seller):
    from api.tests.botkit import load_fixture

    req = {**load_fixture("misc.crm_lead_request.json"), "phone": "+998901119999"}
    loc = req.pop("location", None)
    assert loc
    r1 = bot_client.post("crm/leads/", actor=4001, data=req)
    assert r1.status_code == 201, r1.content
    inv = Invoice.objects.get(pk=r1.data["invoice"]["id"])
    assert inv.lat is None
    r2 = bot_client.post("crm/leads/", actor=4001, data={**req, "location": loc})
    assert r2.status_code == 200 and r2.data["duplicate"] is True
    inv.refresh_from_db()
    assert inv.lat is not None
