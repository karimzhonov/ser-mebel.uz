"""Map locations: lead -> metering -> order inheritance, the panel API, the bot API,
the deadline event and the contract fixtures."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from phonenumber_field.phonenumber import PhoneNumber

from api.tests.botkit import load_fixture
from call_center import dto
from call_center import services as CC
from call_center.constants import NoteKind, SolutionChoice
from call_center.models import Invoice
from core.exceptions import ServiceError
from core.geo import MapPoint
from metering.models import Metering
from metering.services import create_metering, set_metering_location

pytestmark = pytest.mark.django_db

INV_PERMS = ("call_center.view_invoice", "call_center.add_invoice", "call_center.change_invoice")
MET_PERMS = ("metering.view_metering", "metering.change_metering")
P = MapPoint("41.311081", "69.279737")
P2 = MapPoint("40.5", "68.5")
YA = "https://yandex.uz/maps/?ll=69.279737,41.311081&pt=69.279737,41.311081&z=17&l=map"
NOW = datetime(2026, 11, 3, 12, 0)


@pytest.fixture
def seller(make_staff):
    return make_staff(*INV_PERMS, name="Dilfuza", telegram_id=4001)


def mk(seller, phone="+998901112233", **kw):
    return CC.create_invoice(
        fio="Ali", phone=PhoneNumber.from_string(phone, region="UZ"), author=seller, **kw
    )


def mk_metering(inv, **kw):
    return create_metering(client=inv.client, date_time=NOW + timedelta(days=1), invoice=inv, **kw)


# ------------------------------------------------------------------ services
def test_set_invoice_location_is_idempotent_and_logs(seller):
    inv = mk(seller)
    _, changed, filled = CC.set_invoice_location(inv, point=P, by=seller, via="bot")
    assert changed and filled == []
    inv.refresh_from_db()
    assert (inv.lat, inv.lon) == (Decimal("41.311081"), Decimal("69.279737"))
    note = inv.notes.get(kind=NoteKind.location)
    assert note.meta == {"lat": "41.311081", "lon": "69.279737", "link": False, "via": "bot"}
    _, changed, _ = CC.set_invoice_location(inv, point=P, by=seller)
    assert not changed and inv.notes.filter(kind=NoteKind.location).count() == 1
    CC.set_invoice_location(inv, point=P2, by=seller)
    assert inv.notes.filter(kind=NoteKind.location).count() == 2
    inv.refresh_from_db()
    assert inv.solution is None  # attaching a location does not move the lead


def test_clear_and_address_rules(seller):
    inv = mk(seller, address="Chilonzor 5", lat=P.lat, lon=P.lon)
    assert inv.notes.filter(kind=NoteKind.location, meta__via="panel").count() == 1
    # a venue address from the bot never overwrites a typed one
    CC.set_invoice_location(inv, point=P2, address="Venue", by=seller, via="bot")
    inv.refresh_from_db()
    assert inv.address == "Chilonzor 5"
    # the bot never clears it; the panel may, while a point locates the lead
    CC.set_invoice_location(inv, point=P2, address="", by=seller, via="bot")
    inv.refresh_from_db()
    assert inv.address == "Chilonzor 5"
    CC.set_invoice_location(inv, point=P2, address="", by=seller)
    inv.refresh_from_db()
    assert inv.address == ""
    CC.set_invoice_location(inv, point=P2, address="Chilonzor 5", by=seller)
    CC.set_invoice_location(inv, point=None, by=seller)
    inv.refresh_from_db()
    assert inv.lat is None and inv.lon is None and inv.address_link is None
    # a bot venue fills a blank address
    other = mk(seller, "+998901112244")
    CC.set_invoice_location(other, point=P, address="Venue", by=seller, via="bot")
    other.refresh_from_db()
    assert other.address == "Venue"


def test_closed_lead_can_still_get_a_location(seller):
    inv = mk(seller)
    inv.solution = SolutionChoice.declined
    inv.save()
    _, changed, _ = CC.set_invoice_location(inv, point=P, by=seller)
    assert changed


def test_create_invoice_with_location_and_bad_coordinates(seller):
    inv = mk(seller, lat=P.lat, lon=P.lon, address_link="https://yandex.uz/maps/?pt=1,2")
    assert inv.notes.filter(kind=NoteKind.location).count() == 1
    with pytest.raises(ServiceError):
        mk(seller, "+998901112299", lat="95", lon="10")


def test_fill_down_into_metering_and_order_never_overwrites(seller):
    inv = mk(seller)
    m = mk_metering(inv)  # no location yet
    assert m.lat is None
    _, _, filled = CC.set_invoice_location(
        inv, point=P, link="https://yandex.uz/maps/?pt=1,2", address="Chilonzor", by=seller
    )
    assert filled == [("metering", m.pk)]
    m.refresh_from_db()
    assert (m.lat, m.address, m.address_link) == (
        P.lat,
        "Chilonzor",
        "https://yandex.uz/maps/?pt=1,2",
    )
    # a point the metering already has stays
    CC.set_invoice_location(inv, point=P2, by=seller)
    m.refresh_from_db()
    assert m.lat == P.lat


def test_create_metering_inherits_and_own_location_wins(seller):
    inv = mk(seller, address="Chilonzor 5", lat=P.lat, lon=P.lon, address_link="https://x.uz/a")
    m = mk_metering(inv)
    assert (m.lat, m.lon, m.address, m.address_link) == (
        P.lat,
        P.lon,
        "Chilonzor 5",
        "https://x.uz/a",
    )
    inv2 = mk(seller, "+998901112244", lat=P.lat, lon=P.lon)
    m2 = mk_metering(inv2, lat=P2.lat, lon=P2.lon, address="Boshqa")
    assert (m2.lat, m2.address) == (P2.lat, "Boshqa")
    with pytest.raises(ServiceError):
        create_metering(client=inv.client, date_time=NOW, lat="x", lon="1")


def test_set_metering_location_refuses_archived_and_fills_order(seller, admin_api):
    inv = mk(seller)
    m = mk_metering(inv)
    set_metering_location(m, point=P, by=seller)
    m.refresh_from_db()
    assert m.lat == P.lat
    Metering.objects.filter(pk=m.pk).update(status="done")
    m.refresh_from_db()
    with pytest.raises(ServiceError):
        set_metering_location(m, point=P2, by=seller)


def _order_chain(admin_api, phone="+998901112255", **inv_extra):
    """lead -> metering -> done design -> (nothing yet): returns ids."""
    from order.constants import DEFAULT_FACTORY_NAME
    from order.models import Factory

    Factory.objects.get_or_create(name=DEFAULT_FACTORY_NAME)
    r = admin_api.post(
        "/api/v1/invoices/",
        {"fio": "Ali", "phone": phone, "desc": "x", "source": "phone", **inv_extra},
        format="json",
    )
    assert r.status_code == 201, r.content
    inv_id = r.data["id"]
    r = admin_api.post(
        "/api/v1/meterings/",
        {"client_phone": phone, "date_time": "2026-10-25T10:00:00", "invoice": inv_id},
        format="json",
    )
    assert r.status_code == 201, r.content
    mid = r.data["id"]
    admin_api.post(f"/api/v1/meterings/{mid}/metering-done/")
    design = admin_api.post(f"/api/v1/meterings/{mid}/create-design/").data["design"]["id"]
    dtype = admin_api.get(f"/api/v1/designs/{design}/").data["types"][0]["id"]
    admin_api.post(f"/api/v1/designs/{design}/done/")
    return inv_id, mid, dtype


def _order_payload(mid, dtype, **extra):
    return {
        "metering": mid,
        "design_type": dtype,
        "count_days": 30,
        "price": {"amount": 100, "currency": "USD"},
        **extra,
    }


def test_order_inherits_the_metering_location(admin_api):
    inv_id, mid, dtype = _order_chain(
        admin_api, location="https://yandex.ru/maps/?pt=69.279737,41.311081", address="Chilonzor 5"
    )
    r = admin_api.post("/api/v1/orders/", _order_payload(mid, dtype), format="json")
    assert r.status_code == 201, r.content
    assert r.data["lat"] == "41.311081" and r.data["lon"] == "69.279737"
    assert r.data["address"] == "Chilonzor 5" and r.data["map_url"] == YA
    assert r.data["address_link"].startswith("https://yandex.ru/maps/")


def test_order_needs_an_address_or_a_point(admin_api):
    _, mid, dtype = _order_chain(admin_api)
    r = admin_api.post("/api/v1/orders/", _order_payload(mid, dtype), format="json")
    assert r.status_code == 400
    assert "Manzilni kiriting" in str(r.data)
    r = admin_api.post(
        "/api/v1/orders/", _order_payload(mid, dtype, location="41.3, 69.2"), format="json"
    )
    assert r.status_code == 201, r.content
    assert r.data["address"] == "" and r.data["lat"] == "41.300000"


def test_order_own_address_beats_the_metering(admin_api):
    _, mid, dtype = _order_chain(admin_api, address="Metering manzili")
    r = admin_api.post(
        "/api/v1/orders/", _order_payload(mid, dtype, address="Buyurtma manzili"), format="json"
    )
    assert r.status_code == 201, r.content
    assert r.data["address"] == "Buyurtma manzili"


# ------------------------------------------------------------------ panel API
def test_invoice_location_action(api, seller):
    client = api(*INV_PERMS)
    inv = mk(seller)
    url = f"/api/v1/invoices/{inv.pk}/location/"
    r = client.post(
        url,
        {"location": "https://yandex.ru/maps/?pt=69.279737,41.311081", "address": "A"},
        format="json",
    )
    assert r.status_code == 200, r.content
    assert r.data["lat"] == "41.311081" and r.data["map_url"] == YA
    assert r.data["address"] == "A" and r.data["short"] is False
    r = client.post(url, {"location": "https://maps.app.goo.gl/abc"}, format="json")
    assert r.status_code == 200 and r.data["short"] is True and r.data["lat"] is None
    assert r.data["address_link"] == "https://maps.app.goo.gl/abc"
    r = client.post(url, {"location": "hech narsa"}, format="json")
    assert r.status_code == 400 and "location" in r.data
    r = client.post(url, {"location": ""}, format="json")
    assert r.status_code == 200 and r.data["lat"] is None and r.data["address_link"] is None
    # view only -> refused
    viewer = api("call_center.view_invoice")
    assert viewer.post(url, {"location": "41.3, 69.2"}, format="json").status_code == 403


def test_metering_and_order_location_actions(api, seller, admin_api):
    inv_id, mid, dtype = _order_chain(admin_api, address="Metering manzili")
    # an editable metering is needed: use a fresh lead for the metering action
    inv = mk(seller, "+998901112266")
    m = mk_metering(inv)
    client = api(*MET_PERMS)
    r = client.post(
        f"/api/v1/meterings/{m.pk}/location/", {"location": "41.31, 69.27"}, format="json"
    )
    assert r.status_code == 200, r.content
    assert r.data["lat"] == "41.310000" and r.data["short"] is False and r.data["is_editable"]
    assert (
        api("metering.view_metering")
        .post(f"/api/v1/meterings/{m.pk}/location/", {"location": "41.31, 69.27"}, format="json")
        .status_code
        == 403
    )
    # archived metering: service refusal -> 400
    r = admin_api.post(
        f"/api/v1/meterings/{mid}/location/", {"location": "41.31, 69.27"}, format="json"
    )
    assert r.status_code == 200  # metering_done is still editable
    order = admin_api.post("/api/v1/orders/", _order_payload(mid, dtype), format="json")
    assert order.status_code == 201, order.content
    r = admin_api.post(
        f"/api/v1/meterings/{mid}/location/", {"location": "41.0, 69.0"}, format="json"
    )
    assert r.status_code == 400  # sold_out: archived
    oid = order.data["id"]
    r = admin_api.post(
        f"/api/v1/orders/{oid}/location/",
        {"location": "41.2, 69.1", "address": "Yangi"},
        format="json",
    )
    assert r.status_code == 200, r.content
    assert (r.data["lat"], r.data["address"], r.data["short"]) == ("41.200000", "Yangi", False)
    assert (
        api("order.view_order")
        .post(f"/api/v1/orders/{oid}/location/", {"location": "41.2, 69.1"}, format="json")
        .status_code
        == 403
    )


def test_geo_parse_endpoint(api):
    client = api()
    r = client.post("/api/v1/geo/parse/", {"text": "41.311081, 69.279737"}, format="json")
    assert r.status_code == 200
    assert r.data == {"lat": "41.311081", "lon": "69.279737", "map_url": YA, "short": False}
    r = client.post("/api/v1/geo/parse/", {"text": "https://maps.app.goo.gl/abc"}, format="json")
    assert r.data["short"] is True and r.data["lat"] is None
    r = client.post("/api/v1/geo/parse/", {"text": "zzz"}, format="json")
    assert r.status_code == 400 and "location" in r.data
    from rest_framework.test import APIClient

    assert APIClient().post("/api/v1/geo/parse/", {"text": "1,2"}, format="json").status_code in (
        401,
        403,
    )


def test_read_serializers_expose_location(api, seller, admin_api):
    inv = mk(seller, lat=P.lat, lon=P.lon)
    m = mk_metering(inv)
    client = api(*INV_PERMS, *MET_PERMS)
    row = client.get(f"/api/v1/invoices/{inv.pk}/").data
    assert (row["lat"], row["lon"], row["map_url"]) == ("41.311081", "69.279737", YA)
    assert row["address"] == "" and row["address_link"] is None
    det = client.get(f"/api/v1/meterings/{m.pk}/").data
    assert det["lat"] == "41.311081" and det["map_url"] == YA
    # no point and no address -> no map link
    bare = mk(seller, "+998901112277")
    assert client.get(f"/api/v1/invoices/{bare.pk}/").data["map_url"] is None
    # a typed address falls back to a Yandex text search
    Invoice.objects.filter(pk=bare.pk).update(address="Chilonzor 5")
    assert "text=Chilonzor%205" in client.get(f"/api/v1/invoices/{bare.pk}/").data["map_url"]


def test_legacy_address_link_input_is_read_as_a_location(admin_api, seller):
    admin_api.post(
        "/api/v1/invoices/",
        {"fio": "Ali", "phone": "+998901112288", "source": "phone"},
        format="json",
    )
    inv = Invoice.objects.get(client__phone="+998901112288")
    r = admin_api.post(
        "/api/v1/meterings/",
        {
            "client_phone": "+998901112288",
            "date_time": "2026-10-25T10:00:00",
            "address": "A",
            "address_link": "https://yandex.ru/maps/?pt=69.279737,41.311081",
            "invoice": inv.pk,
        },
        format="json",
    )
    assert r.status_code == 201, r.content
    assert r.data["lat"] == "41.311081"
    bad = admin_api.post(
        "/api/v1/meterings/",
        {"client_phone": "+998901112288", "date_time": "2026-10-25T10:00:00", "location": "zzz"},
        format="json",
    )
    assert bad.status_code == 400 and "location" in bad.data


def test_dashboard_cards_carry_map_url(admin_api, seller):
    inv = mk(seller, lat=P.lat, lon=P.lon)
    mk_metering(inv)
    ov = admin_api.get("/api/v1/dashboard/overview/")
    assert ov.status_code == 200
    up = ov.data["meterings"]["upcoming"]
    assert up and up[0]["map_url"] == YA and up[0]["lat"] == "41.311081"
    boards = admin_api.get("/api/v1/dashboard/boards/?board=meterings")
    assert boards.status_code == 200


# ------------------------------------------------------------------ bot API
def test_whoami_can_set_location_combos(bot_client, make_staff):
    cases = [
        (("call_center.view_invoice", "call_center.change_invoice"), True),
        (("metering.view_metering", "metering.change_metering"), True),
        (("call_center.view_invoice",), False),
        (("call_center.change_invoice",), False),
        ((), False),
    ]
    for i, (perms, expected) in enumerate(cases):
        make_staff(*perms, telegram_id=5000 + i)
        who = bot_client.post("whoami/", actor=5000 + i, data={"user": {"id": 5000 + i}})
        assert who.data["crm"]["can_set_location"] is expected, perms
    assert bot_client.post("whoami/", actor=1, data={"user": {"id": 1}}).data["crm"] == {
        "linked": False,
        "can_add_lead": False,
        "can_set_location": False,
    }


def test_location_candidates(bot_client, seller, make_staff):
    boss = make_staff(*INV_PERMS, *MET_PERMS, name="Boss", telegram_id=4100)
    own = mk(seller)
    own.solution = SolutionChoice.given_location
    own.save()
    other = mk(seller, "+998901112244")  # solution None: not "location requested"
    has_pt = mk(seller, "+998901112255", lat=P.lat, lon=P.lon)
    no_pt = mk(seller, "+998901112266")
    m_pt = mk_metering(has_pt)
    m_no = mk_metering(no_pt)
    # archived meterings never show
    done = mk_metering(mk(seller, "+998901112277"))
    Metering.objects.filter(pk=done.pk).update(status="done")

    r = bot_client.get("crm/locations/candidates/", actor=4001)
    assert r.status_code == 200
    assert [(i["kind"], i["id"]) for i in r.data["items"]] == [("invoice", own.pk)]
    assert r.data["items"][0]["mine"] is True and r.data["can_new_lead"] is True

    r = bot_client.get("crm/locations/candidates/", actor=4100)
    items = [(i["kind"], i["id"]) for i in r.data["items"]]
    # boss owns no lead; meterings without a point first
    assert items == [("metering", m_no.pk), ("metering", m_pt.pk)]
    assert r.data["items"][0]["has_point"] is False and r.data["items"][1]["has_point"] is True

    r = bot_client.get("crm/locations/candidates/?phone=%2B998901112244", actor=4001)
    assert [(i["kind"], i["id"]) for i in r.data["items"]] == [("invoice", other.pk)]
    r = bot_client.get("crm/locations/candidates/?phone=%2B998901112266", actor=4100)
    # the lead is already «go_for_measured» (closed for editing): only its metering is offered
    assert [(i["kind"], i["id"]) for i in r.data["items"]] == [("metering", m_no.pk)]
    # closed leads are not offered
    other.solution = SolutionChoice.declined
    other.save()
    r = bot_client.get("crm/locations/candidates/?phone=%2B998901112244", actor=4001)
    assert r.data["items"] == []

    assert bot_client.get("crm/locations/candidates/?phone=12", actor=4001).data["field"] == "phone"
    assert bot_client.get("crm/locations/candidates/", actor=999).status_code == 403
    make_staff("call_center.view_invoice", telegram_id=4200)
    assert bot_client.get("crm/locations/candidates/", actor=4200).status_code == 403
    _ = boss


def test_location_post_invoice_and_fill(bot_client, seller):
    inv = mk(seller)
    m = mk_metering(inv)
    body = {
        "target": {"kind": "invoice", "id": inv.pk},
        "lat": 41.311081,
        "lon": "69.279737",
        "address": "Venue",
        "live": True,
    }
    r = bot_client.post("crm/locations/", actor=4001, data=body)
    assert r.status_code == 200, r.content
    assert r.data["changed"] is True and r.data["filled"] == [{"kind": "metering", "id": m.pk}]
    assert r.data["map_url"] == YA and r.data["url"].endswith(f"/call-center?open={inv.pk}")
    assert r.data["target"]["has_point"] is True and r.data["target"]["address"] == "Venue"
    assert set(r.data) == set(load_fixture("misc.crm_location_response.json"))
    assert set(r.data["target"]) == set(load_fixture("dto.location_target.1.json"))
    again = bot_client.post("crm/locations/", actor=4001, data=body)
    assert again.data["changed"] is False and again.data["filled"] == []
    assert Invoice.objects.get(pk=inv.pk).notes.filter(kind=NoteKind.location).count() == 1


def test_location_post_metering_errors_and_perms(bot_client, seller, make_staff):
    make_staff(*MET_PERMS, telegram_id=4300)
    inv = mk(seller)
    m = mk_metering(inv)
    ok = {"target": {"kind": "metering", "id": m.pk}, "lat": "41.3", "lon": "69.2"}
    r = bot_client.post("crm/locations/", actor=4300, data=ok)
    assert r.status_code == 200, r.content
    assert r.data["url"].endswith(f"/meterings/{m.pk}") and r.data["changed"] is True
    # wrong-kind permission
    wrong = {**ok, "target": {"kind": "invoice", "id": inv.pk}}
    assert bot_client.post("crm/locations/", actor=4300, data=wrong).status_code == 403
    assert bot_client.post("crm/locations/", actor=4001, data=ok).status_code == 403
    for bad in (
        {"lat": "95", "lon": "10"},
        {"lat": "x", "lon": "1"},
        {"lat": "0", "lon": "0"},
        {"lat": None},
    ):
        r = bot_client.post("crm/locations/", actor=4300, data={**ok, **bad})
        assert r.status_code == 400 and r.data["field"] == "location", bad
    r = bot_client.post("crm/locations/", actor=4300, data={**ok, "target": {"kind": "x", "id": 1}})
    assert r.status_code == 400 and r.data["field"] == "target"
    gone = {**ok, "target": {"kind": "metering", "id": 99999}}
    assert bot_client.post("crm/locations/", actor=4300, data=gone).status_code == 404
    Metering.objects.filter(pk=m.pk).update(status="done")
    r = bot_client.post("crm/locations/", actor=4300, data={**ok, "lat": "40", "lon": "68"})
    assert r.status_code == 400 and "detail" in r.data
    assert bot_client.post("crm/locations/", actor=999, data=ok).status_code == 403


def test_bot_lead_create_with_location(bot_client, seller):
    req = {**load_fixture("misc.crm_lead_request.json"), "phone": "+998901119999"}
    r = bot_client.post("crm/leads/", actor=4001, data=req)
    assert r.status_code == 201, r.content
    inv = Invoice.objects.get(pk=r.data["invoice"]["id"])
    assert (inv.lat, inv.lon, inv.address) == (P.lat, P.lon, "Chilonzor 5")
    assert r.data["invoice"]["has_point"] is True and r.data["invoice"]["map_url"] == YA
    assert inv.notes.get(kind=NoteKind.location).meta["via"] == "bot"
    bad = bot_client.post(
        "crm/leads/",
        actor=4001,
        data={**req, "phone": "+998901118888", "location": {"lat": "x", "lon": "1"}},
    )
    assert bad.status_code == 400 and bad.data["field"] == "location"
    # the duplicate branch ignores the location
    dup = bot_client.post(
        "crm/leads/", actor=4001, data={**req, "location": {"lat": "40", "lon": "68"}}
    )
    assert dup.status_code == 200 and dup.data["duplicate"] is True
    inv.refresh_from_db()
    assert inv.lat == P.lat


# ------------------------------------------------------------------ events + fixtures
def test_deadline_event_carries_the_point(members, site_order, bot_events):
    from accounting import events as AE
    from accounting import services as S

    site_order.lat, site_order.lon = P.lat, P.lon
    site_order.save()
    info = S.order_info("406")
    AE.deadline(info, 3, "3", [members[1]], "x")
    order = bot_events.one("finance.deadline")["order"]
    assert (order["lat"], order["lon"], order["map_url"]) == ("41.311081", "69.279737", YA)
    fixture = load_fixture("event.finance.deadline.json")["data"]["order"]
    assert set(order) == set(fixture)
    site_order.lat = site_order.lon = None
    site_order.save()
    AE.deadline(S.order_info("406"), 3, "3", [members[1]], "x")
    last = bot_events.of("finance.deadline")[-1]["order"]
    assert last["lat"] is None and last["lon"] is None
    assert last["map_url"].startswith("https://yandex.uz/maps/?text=Chilonzor")


def test_task_due_event_and_fixtures(seller, bot_events):
    inv = mk(seller, lat=P.lat, lon=P.lon)
    task = CC.create_task(inv, text="x", due_at=NOW, by=seller)
    from call_center import events

    events.task_due(task)
    data = bot_events.one("crm.task_due")
    assert data["invoice"]["map_url"] == YA and data["invoice"]["has_point"] is True
    fixture = load_fixture("event.crm.task_due.json")["data"]
    assert set(data["invoice"]) == set(fixture["invoice"])
    brief = dto.lead_brief(Invoice.objects.select_related("client", "assigned_to").get(pk=inv.pk))
    assert set(brief) == set(load_fixture("dto.lead_brief.1.json"))


def test_location_target_dto_matches_fixture(seller):
    inv = mk(seller)
    inv.solution = SolutionChoice.given_location
    inv.save()
    inv = Invoice.objects.select_related("client").get(pk=inv.pk)
    target = dto.location_target("invoice", inv, seller)
    fixture = load_fixture("dto.location_target.1.json")
    assert set(target) == set(fixture) and set(target["client"]) == set(fixture["client"])
    assert target["status"] == 3 and target["mine"] is True
    m = Metering.objects.select_related("client", "invoice").get(
        pk=mk_metering(mk(seller, "+998901112200")).pk
    )
    mt = dto.location_target("metering", m, seller)
    assert mt["status"] == "created" and mt["mine"] is True and mt["when"].startswith("2026-11-04")
    cand = load_fixture("misc.crm_location_candidates_response.json")
    assert set(cand) == {"items", "can_new_lead"} and set(cand["items"][1]) == set(fixture)
    req = load_fixture("misc.crm_location_request.json")
    assert set(req) == {"target", "lat", "lon", "address", "live"}
    who = load_fixture("misc.whoami_response.json")
    assert who["crm"] == {"linked": True, "can_add_lead": True, "can_set_location": True}
