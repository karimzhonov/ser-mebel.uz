"""Call-centre CRM: notes, tasks, board, timeline, reminders and the bot channel."""

from datetime import datetime, timedelta

import pytest

from api.tests.botkit import load_fixture
from call_center import services as CC
from call_center.constants import NoteKind
from call_center.models import Invoice, InvoiceNote
from core.exceptions import ServiceConflict, ServiceError, ServiceForbidden

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("default_measurer")]

PERMS = ("call_center.view_invoice", "call_center.add_invoice", "call_center.change_invoice")
NOW = datetime(2026, 11, 3, 12, 0)


@pytest.fixture
def seller(make_staff):
    return make_staff(*PERMS, name="Dilfuza", telegram_id=4001)


def lead(seller, phone="+998901112233", **kw):
    from phonenumber_field.phonenumber import PhoneNumber

    return CC.create_invoice(
        fio="Ali", phone=PhoneNumber.from_string(phone, region="UZ"), author=seller, **kw
    )


def test_parse_due_and_presets():
    assert CC.parse_due("14:30", NOW) == datetime(2026, 11, 3, 14, 30)
    assert CC.parse_due("25.12", NOW) == datetime(2026, 12, 25, 10, 0)
    assert CC.parse_due("25.12 09:15", NOW) == datetime(2026, 12, 25, 9, 15)
    assert CC.parse_due("01.01.2027 08:00", NOW) == datetime(2027, 1, 1, 8, 0)
    for bad in ("11:00 ertaga", "", "99.99", "10:00"):
        with pytest.raises(ServiceError):
            CC.parse_due(bad, NOW)
    assert CC.due_preset("1h", NOW + timedelta(seconds=40)) == datetime(2026, 11, 3, 13, 0)
    assert CC.due_preset("today", NOW) == datetime(2026, 11, 3, 18, 0)
    assert CC.due_preset("today", NOW.replace(hour=17, minute=30)) == datetime(2026, 11, 3, 18, 30)
    assert CC.due_preset("tomorrow", NOW) == datetime(2026, 11, 4, 10, 0)
    with pytest.raises(ServiceError):
        CC.due_preset("later", NOW)


def test_create_invoice_via_api_keeps_history(api, seller):
    c = api(*PERMS, name="Boss")
    body = {"fio": "Ali", "phone": "+998901112233", "desc": "Oshxona", "source": "telegram"}
    assert c.post("/api/v1/invoices/", {**body, "source": None}, format="json").status_code == 400
    r = c.post(
        "/api/v1/invoices/",
        {**body, "task_text": "Qo'ng'iroq", "task_due_at": "2026-12-01T10:00:00"},
        format="json",
    )
    assert r.status_code == 201, r.content
    assert r.data["source"] == "telegram" and r.data["assigned_to"]["name"] == "Boss"
    assert r.data["open_tasks"] == 1 and r.data["needs_task"] is False
    assert r.data["next_task"]["text"] == "Qo'ng'iroq"
    inv = Invoice.objects.get(pk=r.data["id"])
    assert inv.desc == "Oshxona" and inv.notes.filter(kind=NoteKind.note).count() == 1
    # editing the description appends a note instead of overwriting history
    r = c.patch(f"/api/v1/invoices/{inv.pk}/", {"desc": "Yangi"}, format="json")
    assert r.status_code == 200 and r.data["desc"] == "Yangi"
    assert inv.notes.count() == 2
    # a task needs both fields or neither
    r = c.post("/api/v1/invoices/", {**body, "task_text": "x"}, format="json")
    assert r.status_code == 400
    # list: filters + annotations
    r = c.get("/api/v1/invoices/?assigned_to=me&source=telegram")
    assert r.status_code == 200
    rows = r.data["results"] if isinstance(r.data, dict) else r.data
    assert [row["open_tasks"] for row in rows] == [1]
    assert c.get("/api/v1/invoices/?assigned_to=none").data["count"] == 0


def test_assignment_requires_an_eligible_person(api, seller, make_staff):
    viewer = make_staff("call_center.view_invoice")
    inv = lead(seller)
    c = api(*PERMS)
    r = c.post(f"/api/v1/invoices/{inv.pk}/assign/", {"assigned_to": viewer.pk}, format="json")
    assert r.status_code == 400
    r = c.post(f"/api/v1/invoices/{inv.pk}/assign/", {"assigned_to": c.user.pk}, format="json")
    assert r.status_code == 200 and r.data["assigned_to"]["id"] == c.user.pk
    note = inv.notes.get(kind=NoteKind.assigned)
    assert note.meta["to_id"] == c.user.pk
    ids = [u["id"] for u in c.get("/api/v1/invoices/assignees/").data]
    assert seller.pk in ids and viewer.pk not in ids


def test_tasks_lifecycle_and_rights(api, seller, make_staff):
    inv = lead(seller)
    other = make_staff(*PERMS)
    task = CC.create_task(inv, text="", due_at=NOW + timedelta(hours=1), by=seller)
    assert task.text == "Mijozga qo'ng'iroq qilish" and task.assigned_to == seller
    with pytest.raises(ServiceForbidden):
        CC.complete_task(task, by=other, outcome="given_info")
    boss = make_staff("call_center.manage_invoice", *PERMS)
    CC.complete_task(task, by=boss, note="Gaplashdik", outcome="given_info")
    with pytest.raises(ServiceConflict):
        CC.complete_task(task, by=seller, outcome="given_info")
    inv.refresh_from_db()
    assert inv.desc == "Gaplashdik"
    timeline = CC.lead_timeline(inv)
    assert [e["type"] for e in timeline][-1] == "created"
    done = next(e for e in timeline if e["type"] == "task_done")
    assert done["text"] == "Gaplashdik"
    assert not any(e["type"] == "note" and e["text"] == "Gaplashdik" for e in timeline)


def test_task_api_agenda_and_reschedule(api, seller, make_staff):
    inv = lead(seller)
    now = datetime.now()
    past = CC.create_task(inv, text="Eski", due_at=now - timedelta(hours=2), by=seller)
    CC.create_task(inv, text="Keyin", due_at=now + timedelta(days=3), by=seller)
    c = api(*PERMS)
    c.force_authenticate(seller)
    r = c.get("/api/v1/invoice-tasks/agenda/")
    assert r.status_code == 200
    assert [t["text"] for t in r.data["overdue"]] == ["Eski"]
    assert [t["text"] for t in r.data["upcoming"]] == ["Keyin"]
    assert c.get("/api/v1/invoice-tasks/summary/").data["overdue"] == 1
    other = api(*PERMS)
    assert other.get(f"/api/v1/invoice-tasks/agenda/?assigned_to={seller.pk}").status_code == 403
    assert (
        other.post(
            f"/api/v1/invoice-tasks/{past.pk}/done/", {"outcome": "given_info"}, format="json"
        ).status_code
        == 400
    )
    r = c.post(
        f"/api/v1/invoice-tasks/{past.pk}/reschedule/", {"preset": "tomorrow"}, format="json"
    )
    assert r.status_code == 200 and r.data["due_at"].endswith("T10:00:00")
    assert (
        c.post(f"/api/v1/invoice-tasks/{past.pk}/reschedule/", {}, format="json").status_code == 400
    )
    assert (
        c.post(
            f"/api/v1/invoice-tasks/{past.pk}/done/",
            {"note": "ok", "outcome": "given_info"},
            format="json",
        ).status_code
        == 200
    )
    assert (
        c.post(
            f"/api/v1/invoice-tasks/{past.pk}/done/", {"outcome": "given_info"}, format="json"
        ).status_code
        == 400
    )


def test_board_and_solution_history(api, seller):
    inv = lead(seller, source="phone")
    c = api(*PERMS)
    r = c.post(f"/api/v1/invoices/{inv.pk}/solution/", {"solution": 1}, format="json")
    assert r.status_code == 200
    assert InvoiceNote.objects.get(invoice=inv, kind=NoteKind.solution).meta == {
        "from": None,
        "to": 1,
    }
    board = c.get("/api/v1/invoices/board/").data["columns"]
    assert [col["key"] for col in board][:6] == [
        "new",
        "re_phone",
        "given_info",
        "given_location",
        "go_for_measured",
        "sold_out",
    ]
    by_key = {col["key"]: col for col in board}
    assert by_key["re_phone"]["count"] == 1 and by_key["re_phone"]["cards"][0]["id"] == inv.pk
    assert by_key["re_phone"]["cards"][0]["needs_task"] is True
    assert by_key["new"]["droppable"] is False and by_key["sold_out"]["droppable"] is False
    assert by_key["declined"]["collapsed"] is True


def test_due_task_reminders_are_sent_once(seller, bot_events, make_staff):
    inv = lead(seller)
    task = CC.create_task(inv, text="Qo'ng'iroq", due_at=NOW - timedelta(minutes=1), by=seller)
    nobody = make_staff(*PERMS)  # no Telegram: skipped but marked
    gone = CC.create_task(
        inv, text="x", due_at=NOW - timedelta(minutes=1), by=seller, assigned_to=nobody
    )
    assert CC.due_task_reminders(NOW) == 1
    assert CC.due_task_reminders(NOW) == 0
    event = bot_events.one("crm.task_due")
    assert event["to"] == [4001] and event["task"]["id"] == task.pk
    assert event["invoice"]["id"] == inv.pk and event["url"].endswith(f"/call-center?open={inv.pk}")
    gone.refresh_from_db()
    assert gone.notified_at is not None
    # moved to a later time: reminds again
    CC.reschedule_task(task, by=seller, due_at=NOW + timedelta(minutes=5))
    assert CC.due_task_reminders(NOW + timedelta(minutes=6)) == 1


# ------------------------------------------------------------------ bot channel
def test_bot_crm_flow(bot_client, seller, bot_events):
    unlinked = bot_client.post("crm/leads/", actor=999, data={})
    assert unlinked.status_code == 403
    assert "ulanmagan" in unlinked.data["detail"]

    who = bot_client.post("whoami/", actor=4001, data={"user": {"id": 4001}})
    assert who.data["crm"] == {"linked": True, "can_add_lead": True, "can_set_location": True}

    req = load_fixture("misc.crm_lead_request.json")
    r = bot_client.post("crm/leads/", actor=4001, data=req)
    assert r.status_code == 201, r.content
    fixture = load_fixture("misc.crm_lead_response.json")
    assert set(r.data) == set(fixture)
    assert set(r.data["invoice"]) == set(fixture["invoice"])
    assert set(r.data["task"]) == set(fixture["task"])
    assert r.data["client_existed"] is False and r.data["invoice"]["assigned"]["id"] == seller.pk
    assert r.data["task"]["due_at"].endswith("T10:00:00")

    lookup = bot_client.get("crm/clients/?phone=%2B998901112244", actor=4001)
    assert lookup.data["exists"] and lookup.data["invoices_count"] == 1
    assert lookup.data["open_invoice"]["id"] == r.data["invoice"]["id"]
    assert bot_client.get("crm/clients/?phone=12", actor=4001).data["field"] == "phone"

    bad = bot_client.post("crm/leads/", actor=4001, data={**req, "source": "x"})
    assert bad.status_code == 400 and bad.data["field"] == "source"
    bad = bot_client.post(
        "crm/leads/", actor=4001, data={**req, "remind": {"at": "2001-01-01T10:00"}}
    )
    assert bad.status_code == 400 and bad.data["field"] == "remind"
    parsed = bot_client.post("crm/due/parse/", actor=4001, data={"text": "zzz"})
    assert parsed.status_code == 400 and parsed.data["field"] == "remind"

    tid = r.data["task"]["id"]
    snoozed = bot_client.post(f"crm/tasks/{tid}/snooze/", actor=4001, data={"preset": "1h"})
    assert snoozed.status_code == 200
    done = bot_client.post(f"crm/tasks/{tid}/done/", actor=4001, data={"outcome": "given_info"})
    assert (
        done.status_code == 200
        and done.data["task"]["is_done"]
        and done.data["by_name"] == "Dilfuza"
    )
    assert (
        bot_client.post(
            f"crm/tasks/{tid}/done/", actor=4001, data={"outcome": "given_info"}
        ).status_code
        == 409
    )
    assert (
        bot_client.post(
            "crm/tasks/99999/done/", actor=4001, data={"outcome": "given_info"}
        ).status_code
        == 404
    )


def test_dtos_match_fixtures(seller):
    from call_center import dto

    inv = lead(seller, source="telegram", desc="Oshxona")
    task = CC.create_task(inv, text="x", due_at=NOW, by=seller)
    brief = dto.lead_brief(Invoice.objects.select_related("client", "assigned_to").get(pk=inv.pk))
    assert set(brief) == set(load_fixture("dto.lead_brief.1.json"))
    assert set(brief["client"]) == {"fio", "phone"}
    assert set(dto.task_dto(task)) == set(load_fixture("dto.crm_task.1.json"))


# ====================================================================== extended coverage
@pytest.fixture
def clock(monkeypatch):
    """Pin call_center.services._now (views, snooze, agenda all read it)."""
    monkeypatch.setattr(CC, "_now", lambda: NOW)
    return NOW


def phone_of(raw):
    from phonenumber_field.phonenumber import PhoneNumber

    return PhoneNumber.from_string(raw, region="UZ")


# ---------------------------------------------------------------- migration 0006
def test_migration_0006_turns_desc_into_first_note(seller):
    import importlib

    from django.apps import apps

    from client.models import Client

    mig = importlib.import_module("call_center.migrations.0006_desc_to_first_note")
    client = Client.objects.create(phone=phone_of("+998909990001"), fio="M")
    full = Invoice.objects.create(client=client, desc="  Eski izoh  ")
    blank = Invoice.objects.create(client=client, desc="   ")
    empty = Invoice.objects.create(client=client, desc="")
    none = Invoice.objects.create(client=client, desc=None)
    mig.desc_to_notes(apps, None)
    note = InvoiceNote.objects.get(invoice=full)
    assert note.text == "Eski izoh" and note.kind == "note" and note.author is None
    assert note.meta == {"migrated": True}
    assert note.created_at == Invoice.objects.get(pk=full.pk).create_date
    for inv in (blank, empty, none):
        assert not InvoiceNote.objects.filter(invoice=inv).exists()
    # the desc cache column is kept
    assert Invoice.objects.get(pk=full.pk).desc == "  Eski izoh  "


# ---------------------------------------------------------------- create_invoice
def test_create_invoice_reuses_client_and_defaults_assignee(seller):
    from client.models import Client

    Client.objects.create(phone=phone_of("+998901112233"), fio="Old Name")
    inv = CC.create_invoice(
        fio="New Name", phone=phone_of("+998901112233"), desc=" Oshxona ", author=seller
    )
    assert Client.objects.count() == 1
    assert Client.objects.get().fio == "Old Name"  # existing name never overwritten
    assert inv.assigned_to == seller and inv.created_by == seller
    note = inv.notes.get()
    assert note.kind == NoteKind.note and note.text == "Oshxona" and note.author == seller
    assert inv.desc == "Oshxona"
    assert inv.source is None


def test_create_invoice_explicit_assignee_and_validation(seller, make_staff):
    other = make_staff(*PERMS)
    viewer = make_staff("call_center.view_invoice")
    inv = lead(seller, assigned_to=other)
    assert inv.assigned_to == other and inv.created_by == seller
    with pytest.raises(ServiceError):
        lead(seller, phone="+998901112299", assigned_to=viewer)
    with pytest.raises(ServiceError):
        lead(seller, phone="+998901112298", source="nope")
    assert Invoice.objects.count() == 1


def test_create_invoice_is_atomic_on_bad_task(seller):
    from client.models import Client

    with pytest.raises(ServiceError):
        CC.create_invoice(
            fio="Z",
            phone=phone_of("+998901119999"),
            desc="izoh",
            author=seller,
            task={"text": "x", "due_at": None},
        )
    assert Invoice.objects.count() == 0 and InvoiceNote.objects.count() == 0
    assert not Client.objects.filter(phone=phone_of("+998901119999")).exists()


def test_create_invoice_with_task_uses_default_text(seller):
    inv = lead(seller, task={"text": None, "due_at": NOW + timedelta(hours=1)})
    task = inv.tasks.get()
    assert task.text == "Mijozga qo'ng'iroq qilish" and task.assigned_to == seller
    assert task.created_by == seller


# ---------------------------------------------------------------- notes
def test_add_note_rules(seller):
    inv = lead(seller)
    for blank in ("", "   ", None):
        with pytest.raises(ServiceError):
            CC.add_note(inv, author=seller, text=blank)
    CC.add_note(inv, author=seller, text="Birinchi")
    inv.refresh_from_db()
    assert inv.desc == "Birinchi"
    CC.add_note(inv, author=seller, text="Tizim", kind=NoteKind.source, meta={"a": 1})
    inv.refresh_from_db()
    assert inv.desc == "Birinchi"  # only plain notes touch the cache


def test_notes_and_tasks_have_no_update_or_delete_endpoints(api, seller):
    inv = lead(seller, desc="x")
    task = CC.create_task(inv, text="t", due_at=NOW, by=seller)
    note = inv.notes.get()
    c = api(*PERMS)
    base = f"/api/v1/invoices/{inv.pk}/notes/"
    for method in ("patch", "put", "delete"):
        assert getattr(c, method)(base).status_code in (
            403,
            405,
        )  # 403: no delete_ perm checked first
        assert getattr(c, method)(f"{base}{note.pk}/").status_code == 404
    for method in ("patch", "put", "delete"):
        assert getattr(c, method)(f"/api/v1/invoice-tasks/{task.pk}/").status_code in (404, 405)
    assert c.delete(f"/api/v1/invoices/{inv.pk}/").status_code in (403, 405)
    assert InvoiceNote.objects.filter(pk=note.pk).exists()


def test_notes_api_and_closed_lead_rules(api, seller):
    inv = lead(seller)
    c = api(*PERMS)
    assert (
        c.post(f"/api/v1/invoices/{inv.pk}/notes/", {"text": "  "}, format="json").status_code
        == 400
    )
    r = c.post(f"/api/v1/invoices/{inv.pk}/notes/", {"text": "Salom"}, format="json")
    assert r.status_code == 201 and r.data["desc"] == "Salom"
    # unchanged desc -> no duplicate note
    count = inv.notes.count()
    r = c.patch(f"/api/v1/invoices/{inv.pk}/", {"desc": "Salom"}, format="json")
    assert r.status_code == 200 and inv.notes.count() == count
    # closed lead: PATCH refused, notes still allowed (design default 5)
    Invoice.objects.filter(pk=inv.pk).update(solution=4)
    assert (
        c.patch(f"/api/v1/invoices/{inv.pk}/", {"desc": "Boshqa"}, format="json").status_code == 403
    )
    assert inv.notes.count() == count
    assert (
        c.post(f"/api/v1/invoices/{inv.pk}/notes/", {"text": "Yopiqda"}, format="json").status_code
        == 201
    )


# ---------------------------------------------------------------- solution logging
def test_set_invoice_solution_logs_and_guards(seller):
    inv = lead(seller)
    CC.set_invoice_solution(inv, 2, author=seller)
    n = inv.notes.get(kind=NoteKind.solution)
    assert n.meta == {"from": None, "to": 2} and n.author == seller
    CC.set_invoice_solution(inv, 2, author=seller)  # same value: no history spam
    assert inv.notes.filter(kind=NoteKind.solution).count() == 1
    CC.set_invoice_solution(inv, 4, author=seller)
    assert inv.notes.filter(kind=NoteKind.solution).order_by("-id")[0].meta == {"from": 2, "to": 4}
    for auto in (5, 6):
        with pytest.raises(ServiceError):
            CC.set_invoice_solution(inv, auto, author=seller)
    Invoice.objects.filter(pk=inv.pk).update(solution=6)
    inv.refresh_from_db()
    with pytest.raises(ServiceError):
        CC.set_invoice_solution(inv, 1, author=seller)


def test_create_metering_logs_solution(seller):
    from metering.services import create_metering

    inv = lead(seller)
    create_metering(
        client=inv.client, date_time=NOW + timedelta(days=1), invoice=inv, author=seller
    )
    note = inv.notes.get(kind=NoteKind.solution)
    assert note.meta == {"from": None, "to": 5} and note.author == seller
    inv.refresh_from_db()
    assert inv.solution == 5


def test_create_order_logs_sold_out(admin_api):
    from order.constants import DEFAULT_FACTORY_NAME
    from order.models import Factory

    Factory.objects.get_or_create(name=DEFAULT_FACTORY_NAME)
    r = admin_api.post(
        "/api/v1/invoices/",
        {"fio": "Ali", "phone": "+998901112255", "desc": "x", "source": "phone"},
        format="json",
    )
    inv_id = r.data["id"]
    r = admin_api.post(
        "/api/v1/meterings/",
        {
            "client_phone": "+998901112255",
            "date_time": "2026-10-25T10:00:00",
            "address": "A",
            "invoice": inv_id,
        },
        format="json",
    )
    assert r.status_code == 201, r.content
    mid = r.data["id"]
    admin_api.post(f"/api/v1/meterings/{mid}/metering-done/")
    design = admin_api.post(f"/api/v1/meterings/{mid}/create-design/").data["design"]["id"]
    dtype = admin_api.get(f"/api/v1/designs/{design}/").data["types"][0]["id"]
    admin_api.post(f"/api/v1/designs/{design}/done/")
    r = admin_api.post(
        "/api/v1/orders/",
        {
            "metering": mid,
            "design_type": dtype,
            "address": "A",
            "count_days": 30,
            "price": {"amount": 100, "currency": "USD"},
            "lost_money": {"amount": 10, "currency": "USD"},
        },
        format="json",
    )
    assert r.status_code == 201, r.content
    inv = Invoice.objects.get(pk=inv_id)
    assert inv.solution == 6
    metas = [n.meta for n in inv.notes.filter(kind=NoteKind.solution).order_by("id")]
    assert metas == [{"from": None, "to": 5}, {"from": 5, "to": 6}]
    assert inv.notes.filter(kind=NoteKind.solution).order_by("id").last().author == admin_api.user


# ---------------------------------------------------------------- update_lead
def test_update_lead_eligibility_and_history(seller, make_staff):
    other = make_staff(*PERMS)
    viewer = make_staff("call_center.view_invoice")
    inv = lead(seller)
    with pytest.raises(ServiceError):
        CC.update_lead(inv, by=seller, assigned_to=viewer)
    inv.refresh_from_db()
    assert inv.assigned_to == seller and not inv.notes.filter(kind=NoteKind.assigned).exists()
    CC.update_lead(inv, by=seller, assigned_to=other, source="instagram")
    inv.refresh_from_db()
    assert inv.assigned_to == other and inv.source == "instagram"
    assert inv.notes.get(kind=NoteKind.assigned).meta["to_id"] == other.pk
    assert inv.notes.get(kind=NoteKind.source).meta == {"from": None, "to": "instagram"}
    # no change -> no history
    CC.update_lead(inv, by=seller, assigned_to=other, source="instagram")
    assert inv.notes.filter(kind__in=[NoteKind.assigned, NoteKind.source]).count() == 2
    # unassign, and bad source
    CC.update_lead(inv, by=seller, assigned_to=None)
    inv.refresh_from_db()
    assert inv.assigned_to is None
    with pytest.raises(ServiceError):
        CC.update_lead(inv, by=seller, source="zzz")
    # closed leads can still be reassigned
    Invoice.objects.filter(pk=inv.pk).update(solution=0)
    inv.refresh_from_db()
    CC.update_lead(inv, by=seller, assigned_to=seller)
    assert Invoice.objects.get(pk=inv.pk).assigned_to == seller


def test_assign_api_source_only_and_perm(api, seller):
    inv = lead(seller)
    c = api(*PERMS)
    r = c.post(f"/api/v1/invoices/{inv.pk}/assign/", {"source": "showroom"}, format="json")
    assert r.status_code == 200 and r.data["source"] == "showroom"
    assert (
        c.post(f"/api/v1/invoices/{inv.pk}/assign/", {"source": "bad"}, format="json").status_code
        == 400
    )
    viewer = api("call_center.view_invoice")
    assert (
        viewer.post(
            f"/api/v1/invoices/{inv.pk}/assign/", {"source": "other"}, format="json"
        ).status_code
        == 403
    )


# ---------------------------------------------------------------- tasks
def test_create_task_assignee_rules(seller, make_staff):
    other = make_staff(*PERMS)
    viewer = make_staff("call_center.view_invoice")
    inv = lead(seller)
    assert CC.create_task(inv, text="a", due_at=NOW, by=other).assigned_to == seller  # invoice's
    assert (
        CC.create_task(inv, text="b", due_at=NOW, by=seller, assigned_to=other).assigned_to == other
    )
    with pytest.raises(ServiceError):
        CC.create_task(inv, text="c", due_at=NOW, by=seller, assigned_to=viewer)
    with pytest.raises(ServiceError):
        CC.create_task(inv, text="d", due_at=None, by=seller)
    long = CC.create_task(inv, text="x" * 600, due_at=NOW, by=seller)
    assert len(long.text) == 500


def test_task_rights_matrix(seller, make_staff):
    inv = lead(seller)
    creator = make_staff(*PERMS)
    stranger = make_staff(*PERMS)
    manager = make_staff("call_center.manage_invoice", *PERMS)
    boss = make_staff(superuser=True)

    def fresh():
        return CC.create_task(inv, text="t", due_at=NOW, by=creator, assigned_to=seller)

    t = fresh()
    with pytest.raises(ServiceForbidden):
        CC.complete_task(t, by=stranger, outcome="given_info")
    with pytest.raises(ServiceForbidden):
        CC.reschedule_task(t, by=stranger, due_at=NOW)
    assert not CC.can_manage_task(None, t)
    for user in (creator, seller, manager, boss):
        assert CC.can_manage_task(user, t)
        assert CC.complete_task(fresh(), by=user, outcome="given_info").task.done_by == user


def test_complete_task_conflict_and_forbidden_precedence(seller, make_staff):
    inv = lead(seller)
    stranger = make_staff(*PERMS)
    t = CC.create_task(inv, text="t", due_at=NOW, by=seller)
    CC.complete_task(t, by=seller, outcome="given_info")
    with pytest.raises(ServiceConflict):
        CC.complete_task(t, by=seller, outcome="given_info")
    with pytest.raises(ServiceConflict):
        CC.reschedule_task(t, by=seller, due_at=NOW + timedelta(hours=1))
    # note not written when the completion is refused
    t2 = CC.create_task(inv, text="t2", due_at=NOW, by=seller)
    with pytest.raises(ServiceForbidden):
        CC.complete_task(t2, by=stranger, note="hack", outcome="given_info")
    assert not inv.notes.filter(text="hack").exists()


def test_reschedule_resets_notified_and_snooze_uses_clock(seller, clock):
    inv = lead(seller)
    t = CC.create_task(inv, text="t", due_at=NOW - timedelta(hours=1), by=seller)
    from call_center.models import InvoiceTask

    InvoiceTask.objects.filter(pk=t.pk).update(notified_at=NOW)
    CC.reschedule_task(t, by=seller, due_at=NOW + timedelta(days=1))
    t.refresh_from_db()
    assert t.notified_at is None and t.due_at == NOW + timedelta(days=1)
    InvoiceTask.objects.filter(pk=t.pk).update(notified_at=NOW)
    CC.snooze_task(t, by=seller, preset="1h")
    t.refresh_from_db()
    assert t.due_at == datetime(2026, 11, 3, 13, 0) and t.notified_at is None
    CC.snooze_task(t, by=seller, preset="tomorrow")
    t.refresh_from_db()
    assert t.due_at == datetime(2026, 11, 4, 10, 0)
    with pytest.raises(ServiceError):
        CC.snooze_task(t, by=seller, preset="today")


def test_parse_due_edge_cases():
    assert CC.parse_due(" 9:05 ", NOW.replace(hour=8)) == datetime(2026, 11, 3, 9, 5)
    assert CC.parse_due("4.11", NOW) == datetime(2026, 11, 4, 10, 0)
    assert CC.parse_due("04.11.2026", NOW) == datetime(2026, 11, 4, 10, 0)
    assert CC.parse_due("1.1.2027 8:00", NOW) == datetime(2027, 1, 1, 8, 0)
    for bad in ("11:00", "12:00", "03.11 11:59", "25:00", "12:75", "31.02", "abc", None):
        with pytest.raises(ServiceError):
            CC.parse_due(bad, NOW)
    # "dd.mm" without year, month already past this year is refused (no year roll-over)
    with pytest.raises(ServiceError):
        CC.parse_due("01.01", NOW)


def test_task_api_matrix(api, seller, make_staff, clock):
    inv = lead(seller)
    t = CC.create_task(inv, text="t", due_at=NOW, by=seller)
    viewer = api("call_center.view_invoice")
    assert viewer.get(f"/api/v1/invoices/{inv.pk}/tasks/").status_code == 200
    r = viewer.post(
        f"/api/v1/invoices/{inv.pk}/tasks/",
        {"text": "x", "due_at": "2026-12-01T10:00:00"},
        format="json",
    )
    assert r.status_code == 403
    # view_invoice is enough to reach it; not the viewer's task -> ServiceForbidden (400 here)
    assert (
        viewer.post(
            f"/api/v1/invoice-tasks/{t.pk}/done/", {"outcome": "given_info"}, format="json"
        ).status_code
        == 400
    )
    assert viewer.get("/api/v1/invoice-tasks/agenda/").status_code == 200
    # not staff -> 403, anonymous -> 401
    from rest_framework.test import APIClient

    assert APIClient().get("/api/v1/invoice-tasks/agenda/").status_code in (401, 403)
    # no view perm -> 403
    assert api().get("/api/v1/invoice-tasks/agenda/").status_code == 403
    # other staff with change but unrelated: 403 (not 409/400)
    stranger = api(*PERMS)
    assert (
        stranger.post(
            f"/api/v1/invoice-tasks/{t.pk}/done/", {"outcome": "given_info"}, format="json"
        ).status_code
        == 400
    )  # ServiceForbidden is a 400 on the site API
    mgr = api("call_center.manage_invoice", *PERMS)
    r = mgr.get(f"/api/v1/invoice-tasks/agenda/?assigned_to={seller.pk}")
    assert r.status_code == 200 and [x["id"] for x in r.data["today"]] == [t.pk]
    assert mgr.get("/api/v1/invoice-tasks/agenda/?assigned_to=999999").status_code == 404
    # creating a task through the API for an ineligible user
    v = make_staff("call_center.view_invoice")
    boss = api(*PERMS)
    r = boss.post(
        f"/api/v1/invoices/{inv.pk}/tasks/",
        {"text": "x", "due_at": "2026-12-01T10:00:00", "assigned_to": v.pk},
        format="json",
    )
    assert r.status_code == 400
    r = boss.post(
        f"/api/v1/invoices/{inv.pk}/tasks/",
        {"text": "x", "due_at": "2026-12-01T10:00:00", "assigned_to": boss.user.pk},
        format="json",
    )
    assert r.status_code == 201 and r.data["assigned"]["id"] == boss.user.pk


def test_agenda_buckets_with_fixed_clock(api, seller, clock):
    inv = lead(seller)
    mk = lambda text, at: CC.create_task(inv, text=text, due_at=at, by=seller)  # noqa: E731
    mk("o", NOW - timedelta(minutes=1))
    mk("t1", NOW + timedelta(hours=11))  # 23:00 today
    mk("t2", NOW)  # exactly now -> today bucket (>= now)
    mk("u", datetime(2026, 11, 4, 0, 0))
    done = mk("d", NOW - timedelta(days=1))
    CC.complete_task(done, by=seller, outcome="given_info")
    c = api(*PERMS)
    c.force_authenticate(seller)
    r = c.get("/api/v1/invoice-tasks/agenda/")
    assert [x["text"] for x in r.data["overdue"]] == ["o"]
    assert [x["text"] for x in r.data["today"]] == ["t2", "t1"]
    assert [x["text"] for x in r.data["upcoming"]] == ["u"]
    assert r.data["today"][0]["invoice"]["client"]["fio"] == "Ali"
    assert c.get("/api/v1/invoice-tasks/summary/").data == {"overdue": 1, "today": 2}


# ---------------------------------------------------------------- reminders
def test_reminders_skip_inactive_and_future_and_done(seller, bot_events, make_staff):
    inv = lead(seller)
    gone = make_staff(*PERMS, telegram_id=4999)
    from oauth.models import User

    User.objects.filter(pk=gone.pk).update(is_active=False)
    gone = User.objects.get(pk=gone.pk)
    past = NOW - timedelta(minutes=1)
    CC.create_task(inv, text="inactive", due_at=past, by=seller, assigned_to=gone, check=False)
    CC.create_task(inv, text="future", due_at=NOW + timedelta(minutes=1), by=seller)
    done = CC.create_task(inv, text="done", due_at=past, by=seller)
    CC.complete_task(done, by=seller, outcome="given_info")
    assert CC.due_task_reminders(NOW) == 0
    assert bot_events.of("crm.task_due") == []


def test_reminder_event_matches_fixture(seller, bot_events):
    inv = lead(seller, source="telegram", desc="Oshxona")
    CC.create_task(inv, text="Qo'ng'iroq", due_at=NOW - timedelta(minutes=1), by=seller)
    assert CC.due_task_reminders(NOW) == 1
    fixture = load_fixture("event.crm.task_due.json")
    data = bot_events.one("crm.task_due")
    assert set(data) == set(fixture.get("data", fixture))
    assert data["invoice"]["last_note"] == "Oshxona"


def test_celery_task_wrapper_runs_reminders(seller, bot_events, monkeypatch):
    from call_center import tasks

    inv = lead(seller)
    CC.create_task(inv, text="t", due_at=datetime(2000, 1, 1), by=seller)
    assert tasks.task_reminders() == 1
    assert tasks.task_reminders() == 0


def test_schedule_registers_crm_reminders():
    from django_celery_beat.models import CrontabSchedule, PeriodicTask

    from accounting.schedule import sync_periodic_tasks

    stale = PeriodicTask.objects.create(
        name="old crm",
        task="call_center.tasks.removed",
        crontab=CrontabSchedule.objects.create(minute="5"),
    )
    sync_periodic_tasks()
    sync_periodic_tasks()
    pt = PeriodicTask.objects.get(name="crm: vazifa eslatmalari")
    assert pt.task == "call_center.tasks.task_reminders" and pt.crontab.minute == "*"
    assert PeriodicTask.objects.filter(name="crm: vazifa eslatmalari").count() == 1
    assert not PeriodicTask.objects.filter(pk=stale.pk).exists()


# ---------------------------------------------------------------- API: list / board / stats / timeline
def test_list_annotations_filters_and_needs_task(api, seller, make_staff):
    other = make_staff(*PERMS)
    a = lead(seller, phone="+998901110001", source="telegram")
    b = lead(seller, phone="+998901110002", source="phone", assigned_to=other)
    CC.set_invoice_solution(a, 1, author=seller)
    CC.set_invoice_solution(b, 4, author=seller)  # closed-ish: never needs a task
    late = CC.create_task(a, text="late", due_at=NOW + timedelta(days=2), by=seller)
    CC.create_task(a, text="early", due_at=NOW + timedelta(days=1), by=seller)
    done = CC.create_task(a, text="done", due_at=NOW - timedelta(days=1), by=seller)
    CC.complete_task(done, by=seller, outcome="given_info")
    c = api(*PERMS)

    def rows(qs=""):
        r = c.get(f"/api/v1/invoices/{qs}")
        assert r.status_code == 200
        return {row["id"]: row for row in (r.data["results"] if "results" in r.data else r.data)}

    got = rows()
    assert got[a.pk]["open_tasks"] == 2 and got[a.pk]["next_task"]["text"] == "early"
    assert got[a.pk]["needs_task"] is False
    assert got[b.pk]["open_tasks"] == 0 and got[b.pk]["next_task"] is None
    assert got[b.pk]["needs_task"] is False  # solution 4 is not an active answer
    c2 = lead(seller, phone="+998901110003")
    assert rows()[c2.pk]["needs_task"] is True  # new lead without a task
    assert set(rows(f"?assigned_to={other.pk}")) == {b.pk}
    assert set(rows("?assigned_to=none")) == set()
    assert set(rows("?source=telegram,phone")) == {
        a.pk,
        b.pk,
    }
    assert set(rows("?source=instagram")) == set()
    assert set(rows("?solution=new")) == {c2.pk}
    assert set(rows("?solution=2,4")) == {a.pk, b.pk}  # a moved to given_info by the done
    assert late.pk  # silence unused


def test_stats_still_work_with_new_filters(api, seller):
    a = lead(seller, source="phone")
    lead(seller, phone="+998901110005", source="telegram")
    CC.set_invoice_solution(a, 1, author=seller)
    c = api(*PERMS)
    r = c.get("/api/v1/invoices/stats/")
    assert r.status_code == 200 and r.data["total"] == 2
    by = {row["key"]: row["count"] for row in r.data["by_solution"]}
    assert by["new"] == 1 and by["1"] == 1


def test_stats_follow_source_and_assignee_filters(api, seller):
    """BUG (reported): the SPA's LeadList passes assigned_to/source to /invoices/stats/ but
    InvoiceViewSet.stats groups base_queryset(), which has no such filters."""
    lead(seller, source="phone")
    lead(seller, phone="+998901110005", source="telegram")
    c = api(*PERMS)
    assert c.get("/api/v1/invoices/stats/?source=phone").data["total"] == 1
    assert c.get("/api/v1/invoices/stats/?assigned_to=none").data["total"] == 0


def test_board_shape_limits_and_filters(api, seller):
    a = lead(seller, source="phone")
    b = lead(seller, phone="+998901110006", source="telegram")
    CC.set_invoice_solution(b, 2, author=seller)
    c = api(*PERMS)
    cols = c.get("/api/v1/invoices/board/").data["columns"]
    assert [x["key"] for x in cols] == [
        "new", "re_phone", "given_info", "given_location", "go_for_measured",
        "sold_out", "price_problem", "dont_need", "declined",
    ]  # fmt: skip
    by = {x["key"]: x for x in cols}
    assert by["new"]["solution"] is None and by["given_info"]["solution"] == 2
    assert by["go_for_measured"]["droppable"] is True and by["sold_out"]["droppable"] is False
    assert by["new"]["cards"][0]["id"] == a.pk and by["given_info"]["cards"][0]["id"] == b.pk
    assert set(by["new"]["cards"][0]) >= {"next_task", "open_tasks", "needs_task", "source_label"}
    only = c.get("/api/v1/invoices/board/?source=telegram").data["columns"]
    assert sum(x["count"] for x in only) == 1
    assert api().get("/api/v1/invoices/board/").status_code == 403


def test_board_card_limit(seller):
    for i in range(3):
        lead(seller, phone=f"+99890111100{i}")
    cols = {c["key"]: c for c in CC.lead_board(Invoice.objects.all(), limit_active=2)}
    assert cols["new"]["count"] == 3 and len(cols["new"]["cards"]) == 2


def test_timeline_order_and_content(api, seller):
    from call_center.models import InvoiceTask
    from metering.services import create_metering

    inv = lead(seller, desc="Birinchi")
    base = datetime(2026, 10, 1, 9, 0)
    InvoiceNote.objects.filter(invoice=inv).update(created_at=base + timedelta(minutes=1))
    task = CC.create_task(inv, text="Qo'ng'iroq", due_at=base + timedelta(days=1), by=seller)
    InvoiceTask.objects.filter(pk=task.pk).update(created_at=base + timedelta(hours=1))
    CC.complete_task(task, by=seller, note="Gaplashdik", outcome="given_info")
    InvoiceTask.objects.filter(pk=task.pk).update(done_at=base + timedelta(hours=3))
    InvoiceNote.objects.filter(task=task).update(created_at=base + timedelta(hours=3))
    # completing the task moved the lead to "given_info" (its history line: hour 2)
    InvoiceNote.objects.filter(kind=NoteKind.solution).update(created_at=base + timedelta(hours=2))
    create_metering(
        client=inv.client, date_time=base + timedelta(days=5), invoice=inv, author=seller
    )
    from metering.models import Metering

    Metering.objects.update(create_date=base + timedelta(hours=4))
    Invoice.objects.filter(pk=inv.pk).update(create_date=base)
    InvoiceNote.objects.filter(kind=NoteKind.solution, meta__to=5).update(
        created_at=base + timedelta(hours=4)
    )

    c = api(*PERMS)
    r = c.get(f"/api/v1/invoices/{inv.pk}/timeline/")
    assert r.status_code == 200
    kinds = [(e["type"], e["kind"]) for e in r.data]
    assert kinds == [
        ("note", "solution"),  # -> 5, hour 4
        ("metering", None),  # hour 4 (stable sort keeps note first)
        ("task_done", None),
        ("note", "solution"),  # -> 2 (task outcome), hour 2
        ("task_created", None),
        ("note", "note"),
        ("created", None),
    ]
    ats = [e["at"] for e in r.data]
    assert ats == sorted(ats, reverse=True)
    done = next(e for e in r.data if e["type"] == "task_done")
    assert (
        done["text"] == "Gaplashdik"
        and done["task"]["is_done"]
        and done["author"]["name"] == "Dilfuza"
    )
    assert set(done) == {"type", "at", "author", "kind", "text", "meta", "task", "link"}
    met = next(e for e in r.data if e["type"] == "metering")
    assert met["link"]["kind"] == "metering"
    assert r.data[-1]["type"] == "created" and r.data[-1]["author"]["id"] == seller.pk
    assert api().get(f"/api/v1/invoices/{inv.pk}/timeline/").status_code == 403


def test_timeline_query_count_is_bounded(seller, django_assert_max_num_queries):
    inv = lead(seller, desc="x")
    for i in range(10):
        CC.create_task(inv, text=f"t{i}", due_at=NOW, by=seller)
        CC.add_note(inv, author=seller, text=f"n{i}")
    with django_assert_max_num_queries(8):
        CC.lead_timeline(Invoice.objects.get(pk=inv.pk))


def test_assignees_endpoint_shape(api, seller, make_staff):
    make_staff("call_center.view_invoice", name="Viewer")
    c = api("call_center.view_invoice")
    r = c.get("/api/v1/invoices/assignees/")
    assert r.status_code == 200
    row = next(x for x in r.data if x["id"] == seller.pk)
    assert row == {"id": seller.pk, "name": "Dilfuza", "has_telegram": True}
    assert all(x["name"] != "Viewer" for x in r.data)


def test_create_via_api_permission_and_source_required(api):
    viewer = api("call_center.view_invoice")
    body = {"fio": "A", "phone": "+998901119911", "source": "phone"}
    assert viewer.post("/api/v1/invoices/", body, format="json").status_code == 403
    adder = api("call_center.view_invoice", "call_center.add_invoice")
    assert (
        adder.post(
            "/api/v1/invoices/", {k: v for k, v in body.items() if k != "source"}, format="json"
        ).status_code
        == 400
    )
    assert (
        adder.post("/api/v1/invoices/", {**body, "source": "bad"}, format="json").status_code == 400
    )
    assert adder.post("/api/v1/invoices/", body, format="json").status_code == 201


# ---------------------------------------------------------------- oauth.access
def test_call_center_manager_section(admin_api, make_staff):
    from oauth.access import SECTIONS

    sec = next(s for s in SECTIONS if s.key == "call_center_manager")
    assert sec.edit is False
    u = make_staff()
    r = admin_api.post(
        f"/api/v1/users/{u.pk}/access/", {"levels": {"call_center_manager": "view"}}, format="json"
    )
    assert r.status_code == 200, r.data
    from oauth.models import User

    assert User.objects.get(pk=u.pk).has_perm("call_center.manage_invoice")
    r = admin_api.post(
        f"/api/v1/users/{u.pk}/access/", {"levels": {"call_center_manager": "edit"}}, format="json"
    )
    assert r.status_code == 400
    admin_api.post(
        f"/api/v1/users/{u.pk}/access/", {"levels": {"call_center_manager": "none"}}, format="json"
    )
    assert not User.objects.get(pk=u.pk).has_perm("call_center.manage_invoice")
    # the call_center section does not leak the new models
    cc = next(s for s in SECTIONS if s.key == "call_center")
    assert cc.models == ("call_center.invoice",)


# ---------------------------------------------------------------- bot API
def test_bot_whoami_and_permission_matrix(bot_client, seller, make_staff):
    make_staff("call_center.view_invoice", telegram_id=4002)
    who = bot_client.post("whoami/", actor=4002, data={"user": {"id": 4002}})
    assert who.data["crm"]["can_add_lead"] is False
    assert (
        bot_client.post("whoami/", actor=555, data={"user": {"id": 555}}).data["crm"][
            "can_add_lead"
        ]
        is False
    )
    body = {
        "name": "A",
        "phone": "+998901117711",
        "source": "phone",
        "note": "",
        "remind": {"preset": "none"},
    }
    r = bot_client.post("crm/leads/", actor=4002, data=body)
    assert r.status_code == 403
    # parsing a time is open to anyone who can see leads (the task-done flow needs it)
    assert bot_client.post("crm/due/parse/", actor=4002, data={"text": "23:59"}).status_code in (
        200,
        400,
    )
    nobody = make_staff(telegram_id=4003)
    assert nobody.pk
    assert bot_client.post("crm/due/parse/", actor=4003, data={"text": "23:59"}).status_code == 403
    assert bot_client.get("crm/clients/?phone=%2B998901117711", actor=4002).status_code == 200
    assert bot_client.get("crm/clients/?phone=%2B998901117711", actor=999).status_code == 403
    # a linked but non-staff account is not a panel user
    from oauth.models import User

    User.objects.filter(telegram_id=4002).update(is_staff=False)
    assert bot_client.get("crm/clients/?phone=%2B998901117711", actor=4002).status_code == 403


def test_bot_lead_validation_fields(bot_client, seller):
    ok = {
        "name": "Ali",
        "phone": "+998901117722",
        "source": "phone",
        "note": "",
        "remind": {"preset": "none"},
    }

    def post(**over):
        return bot_client.post("crm/leads/", actor=4001, data={**ok, **over})

    r = post(name="  ")
    assert r.status_code == 400 and r.data["field"] == "name"
    r = post(phone="123")
    assert r.status_code == 400 and r.data["field"] == "phone"
    for junk in ("abc", ""):
        r = post(phone=junk)
        assert r.status_code == 400 and r.data == {
            "detail": "Telefon raqami noto'g'ri",
            "field": "phone",
        }
    assert bot_client.get("crm/clients/?phone=abc", actor=4001).status_code == 400
    r = post(source=None)
    assert r.data["field"] == "source"
    r = post(remind={"preset": "yesterday"})
    assert r.data["field"] == "remind"
    r = post(remind="tomorrow")
    assert r.data["field"] == "remind"
    r = post(remind={"at": "garbage"})
    assert r.data["field"] == "remind"
    assert Invoice.objects.count() == 0
    r = post()
    assert r.status_code == 201 and r.data["task"] is None and r.data["invoice"]["last_note"] == ""
    # same phone again (not a retry: the first lead is old): client existed, name kept
    Invoice.objects.update(create_date=datetime.now() - timedelta(hours=1))
    r = post(name="Boshqa", note="Ikkinchi", remind={"preset": "tomorrow"})
    assert r.status_code == 201 and r.data["client_existed"] is True
    assert (
        r.data["invoice"]["client"]["fio"] == "Ali" and r.data["invoice"]["last_note"] == "Ikkinchi"
    )
    assert r.data["task"]["assigned"]["id"] == seller.pk


def test_bot_clients_lookup_and_due_parse(bot_client, seller, clock):
    unknown = bot_client.get("crm/clients/?phone=%2B998901118800", actor=4001)
    assert unknown.data == {"exists": False, "fio": None, "invoices_count": 0, "open_invoice": None}
    inv = lead(seller, phone="+998901118800")
    closed = lead(seller, phone="+998901118800")
    Invoice.objects.filter(pk=closed.pk).update(solution=0)
    r = bot_client.get("crm/clients/?phone=%2B998901118800", actor=4001)
    assert r.data["exists"] and r.data["fio"] == "Ali" and r.data["invoices_count"] == 2
    assert r.data["open_invoice"]["id"] == inv.pk
    ok = bot_client.post("crm/due/parse/", actor=4001, data={"text": "25.12 14:00"})
    assert ok.status_code == 200 and ok.data == {"due_at": "2026-12-25T14:00:00"}
    past = bot_client.post("crm/due/parse/", actor=4001, data={"text": "10:00"})
    assert past.status_code == 400 and past.data["field"] == "remind"


def test_bot_done_snooze_forbidden_and_conflict(bot_client, seller, make_staff, clock):
    make_staff(*PERMS, telegram_id=4003)  # unrelated colleague
    make_staff("call_center.view_invoice", telegram_id=4004)  # no change perm
    inv = lead(seller)
    t = CC.create_task(inv, text="t", due_at=NOW, by=seller)
    for path in (f"crm/tasks/{t.pk}/done/", f"crm/tasks/{t.pk}/snooze/"):
        assert bot_client.post(path, actor=4003, data={"preset": "1h"}).status_code == 403
        assert bot_client.post(path, actor=4004, data={"preset": "1h"}).status_code == 403
        assert bot_client.post(path, actor=999, data={"preset": "1h"}).status_code == 403
    bad = bot_client.post(f"crm/tasks/{t.pk}/snooze/", actor=4001, data={"preset": "week"})
    assert bad.status_code == 400
    r = bot_client.post(f"crm/tasks/{t.pk}/snooze/", actor=4001, data={"preset": "tomorrow"})
    assert r.status_code == 200 and r.data["task"]["due_at"] == "2026-11-04T10:00:00"
    r = bot_client.post(
        f"crm/tasks/{t.pk}/done/", actor=4001, data={"note": "ok", "outcome": "given_info"}
    )
    assert r.status_code == 200 and r.data["task"]["is_done"] is True
    assert Invoice.objects.get(pk=inv.pk).desc == "ok"
    assert (
        bot_client.post(f"crm/tasks/{t.pk}/snooze/", actor=4001, data={"preset": "1h"}).status_code
        == 409
    )
    assert (
        bot_client.post(
            f"crm/tasks/{t.pk}/done/", actor=4001, data={"outcome": "given_info"}
        ).status_code
        == 409
    )
    assert (
        bot_client.post("crm/tasks/99999/snooze/", actor=4001, data={"preset": "1h"}).status_code
        == 404
    )


def test_bot_manager_can_close_other_peoples_task(bot_client, seller, make_staff, clock):
    make_staff("call_center.manage_invoice", *PERMS, telegram_id=4005, name="Rahbar")
    inv = lead(seller)
    t = CC.create_task(inv, text="t", due_at=NOW, by=seller)
    r = bot_client.post(f"crm/tasks/{t.pk}/done/", actor=4005, data={"outcome": "given_info"})
    assert r.status_code == 200 and r.data["by_name"] == "Rahbar"


def test_bot_request_fixture_roundtrip_remind_at(bot_client, seller, clock):
    req = load_fixture("misc.crm_lead_request.json")
    req = {**req, "remind": {"at": "2026-11-05T09:30"}}
    r = bot_client.post("crm/leads/", actor=4001, data=req)
    assert r.status_code == 201 and r.data["task"]["due_at"] == "2026-11-05T09:30:00"
    assert r.data["url"].endswith(f"/call-center?open={r.data['invoice']['id']}")


# ------------------------------------------------------------------ fix round
def test_retried_lead_post_returns_existing_lead(bot_client, seller):
    body = {
        "name": "Ali",
        "phone": "+998901117733",
        "source": "phone",
        "note": "Birinchi",
        "remind": {"preset": "tomorrow"},
    }
    first = bot_client.post("crm/leads/", actor=4001, data=body)
    assert first.status_code == 201 and "duplicate" not in first.data
    again = bot_client.post("crm/leads/", actor=4001, data=body)
    assert again.status_code == 200 and again.data["duplicate"] is True
    assert again.data["invoice"]["id"] == first.data["invoice"]["id"]
    assert again.data["task"]["id"] == first.data["task"]["id"]
    assert Invoice.objects.count() == 1
    # an older lead is not a retry
    Invoice.objects.update(create_date=datetime.now() - timedelta(minutes=11))
    assert bot_client.post("crm/leads/", actor=4001, data=body).status_code == 201


def test_bot_non_dict_body_is_400(bot_client, seller):
    for path in ("crm/leads/", "crm/due/parse/"):
        assert bot_client.post(path, actor=4001, data=["x"]).status_code == 400


def test_whoami_can_add_lead_needs_view_and_add(bot_client, make_staff):
    make_staff("call_center.add_invoice", telegram_id=4010)
    who = bot_client.post("whoami/", actor=4010, data={"user": {"id": 4010}})
    assert who.data["crm"]["can_add_lead"] is False


def test_assignee_with_view_only_can_close_own_task(api, bot_client, seller, make_staff, clock):
    viewer = make_staff("call_center.view_invoice", telegram_id=4011)
    other = make_staff("call_center.view_invoice")
    inv = lead(seller)
    CC.create_task(inv, text="a", due_at=NOW, by=seller, assigned_to=viewer, check=False)
    t2 = CC.create_task(inv, text="b", due_at=NOW, by=seller, assigned_to=viewer, check=False)
    t3 = CC.create_task(inv, text="c", due_at=NOW, by=seller, assigned_to=viewer, check=False)
    r = bot_client.post(f"crm/tasks/{t2.pk}/done/", actor=4011, data={})
    assert r.status_code == 200
    r = bot_client.post(f"crm/tasks/{t3.pk}/snooze/", actor=4011, data={"preset": "1h"})
    assert r.status_code == 200
    c = api()
    c.force_authenticate(viewer)
    t4 = CC.create_task(inv, text="d", due_at=NOW, by=seller, assigned_to=viewer, check=False)
    assert c.post(f"/api/v1/invoice-tasks/{t4.pk}/done/", {}, format="json").status_code == 200
    t5 = CC.create_task(inv, text="e", due_at=NOW, by=seller, assigned_to=viewer, check=False)
    r = c.post(f"/api/v1/invoice-tasks/{t5.pk}/reschedule/", {"preset": "1h"}, format="json")
    assert r.status_code == 200
    c.force_authenticate(other)  # view only, not theirs
    assert c.post(f"/api/v1/invoice-tasks/{t5.pk}/done/", {}, format="json").status_code == 400


def test_task_serializer_has_created_by(api, seller):
    inv = lead(seller)
    CC.create_task(inv, text="t", due_at=NOW, by=seller)
    c = api(*PERMS)
    r = c.get(f"/api/v1/invoices/{inv.pk}/tasks/")
    assert r.status_code == 200 and r.data[0]["created_by"]["id"] == seller.pk


def test_reminder_is_conditional_and_once_per_reschedule(seller, bot_events):
    inv = lead(seller)
    t = CC.create_task(inv, text="t", due_at=NOW - timedelta(minutes=1), by=seller)
    assert CC.due_task_reminders(NOW) == 1
    # moved and due again, even to the same minute-of-day after a reschedule: reminds again
    CC.reschedule_task(t, by=seller, due_at=NOW - timedelta(minutes=1))
    t.refresh_from_db()
    assert t.remind_seq == 1 and t.notified_at is None
    assert CC.due_task_reminders(NOW) == 1
    assert len(bot_events.of("crm.task_due")) == 2 if hasattr(bot_events, "of") else True


def test_related_has_no_n_plus_one(api, seller, django_assert_max_num_queries):
    from client.models import Client

    for _ in range(4):
        i = lead(seller)
        CC.create_task(i, text="t", due_at=NOW, by=seller)
    c = api(*PERMS, "client.view_client")
    with django_assert_max_num_queries(12):
        r = c.get(f"/api/v1/clients/{Client.objects.first().pk}/related/")
    assert r.status_code == 200 and len(r.data["invoices"]) == 4
    assert r.data["invoices"][0]["open_tasks"] == 1


def test_serializer_fallback_is_memoized(seller):
    from api.serializers.clients import InvoiceSerializer

    inv = lead(seller)
    ser = InvoiceSerializer(Invoice.objects.select_related("client", "assigned_to").get(pk=inv.pk))
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as ctx:
        ser.data
    assert sum("call_center_invoicetask" in q["sql"] for q in ctx.captured_queries) == 1


def test_solution_rechecks_served_under_lock(seller):
    inv = lead(seller)
    stale = Invoice.objects.get(pk=inv.pk)
    Invoice.objects.filter(pk=inv.pk).update(solution=6)
    with pytest.raises(ServiceError):
        CC.set_invoice_solution(stale, 1, author=seller)
    assert Invoice.objects.get(pk=inv.pk).solution == 6


def test_blank_desc_patch_is_ignored(api, seller):
    inv = lead(seller, desc="Eski")
    c = api(*PERMS)
    r = c.patch(f"/api/v1/invoices/{inv.pk}/", {"desc": "  "}, format="json")
    assert r.status_code == 200
    assert inv.notes.count() == 1


def test_create_with_blank_task_text_and_no_due(api):
    c = api(*PERMS)
    r = c.post(
        "/api/v1/invoices/",
        {"fio": "A", "phone": "+998901119911", "source": "phone", "task_text": ""},
        format="json",
    )
    assert r.status_code == 201 and r.data["open_tasks"] == 0


def test_migration_0006_reverse_removes_migrated_notes(seller):
    import importlib

    m = importlib.import_module("call_center.migrations.0006_desc_to_first_note")
    from django.apps import apps

    inv = lead(seller, desc="Salom")
    InvoiceNote.objects.create(invoice=inv, kind="note", text="x", meta={"migrated": True})
    m.drop_migrated_notes(apps, None)
    assert list(inv.notes.values_list("text", flat=True)) == ["Salom"]


def test_reassign_moves_open_tasks_and_create_task_falls_back(seller, make_staff):
    new = make_staff(*PERMS)
    inv = lead(seller)
    mine = CC.create_task(inv, text="a", due_at=NOW, by=seller)
    done = CC.create_task(inv, text="b", due_at=NOW, by=seller)
    CC.complete_task(done, by=seller, outcome="given_info")
    CC.update_lead(inv, by=seller, assigned_to=new)
    mine.refresh_from_db()
    done.refresh_from_db()
    assert mine.assigned_to == new and done.assigned_to == seller
    assert inv.notes.get(kind=NoteKind.assigned).meta["moved_tasks"] == 1
    # the owner lost his rights: a task falls back to the author
    from oauth.models import User

    User.objects.filter(pk=new.pk).update(is_staff=False)
    inv.refresh_from_db()
    t = CC.create_task(inv, text="c", due_at=NOW, by=seller)
    assert t.assigned_to == seller


def test_agenda_query_count_does_not_grow_with_tasks(api, seller, django_assert_max_num_queries):
    now = datetime.now()
    for k in range(6):
        i = lead(seller)
        CC.create_task(i, text="o", due_at=now - timedelta(hours=k + 1), by=seller)
        CC.create_task(i, text="u", due_at=now + timedelta(days=k + 2), by=seller)
    c = api(*PERMS)
    c.force_authenticate(seller)
    with django_assert_max_num_queries(10):
        r = c.get("/api/v1/invoice-tasks/agenda/")
    assert r.status_code == 200 and len(r.data["overdue"]) == 6
    assert r.data["overdue"][0]["created_by"]["id"] == seller.pk
