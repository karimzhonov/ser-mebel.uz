"""Zamer stage 1: measurers, the measurer's actions, reminders, the site API."""

from api.tests.accesskit import set_levels  # noqa: E402

from datetime import datetime, timedelta

import pytest
from django.contrib.auth.models import Group, Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from phonenumber_field.phonenumber import PhoneNumber

from api.tests.offerkit import design_file
from call_center import services as CC
from call_center.constants import NoteKind, SolutionChoice
from call_center.models import InvoiceTask
from core.exceptions import ServiceConflict, ServiceError, ServiceForbidden
from metering import services as M
from metering.constants import MeteringStatus
from metering.models import Metering

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 11, 3, 12, 0)  # a Tuesday
TOMORROW_10 = datetime(2026, 11, 4, 10, 0)
PDF = b"%PDF-1.4\n%test\n"
MEASURER_PERMS = ("oauth.user_metering", "metering.view_metering")
OPERATOR_PERMS = (
    "call_center.view_invoice",
    "call_center.add_invoice",
    "call_center.change_invoice",
    "metering.view_metering",
    "metering.add_metering",
    "metering.change_metering",
)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    now = {"v": NOW}
    monkeypatch.setattr(M, "_now", lambda: now["v"])
    monkeypatch.setattr(CC, "_now", lambda: now["v"])
    return now


@pytest.fixture(autouse=True)
def sms_calls(monkeypatch):
    calls = []
    monkeypatch.setattr("metering.tasks.assignment_sms.delay", lambda *a: calls.append(a))
    return calls


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)


@pytest.fixture
def commit(django_capture_on_commit_callbacks):
    def _run(fn, *args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return fn(*args, **kwargs)

    return _run


@pytest.fixture
def ali(make_staff):
    """The only measurer, linked to Telegram."""
    return make_staff(*MEASURER_PERMS, name="Ali", telegram_id=7001)


@pytest.fixture
def operator(make_staff):
    return make_staff(*OPERATOR_PERMS, name="Dilfuza", telegram_id=4001)


@pytest.fixture
def boss(make_staff):
    return make_staff(*OPERATOR_PERMS, "metering.manage_metering", name="Boss", telegram_id=4002)


def lead(operator, phone="+998901112233"):
    return CC.create_invoice(
        fio="Karim", phone=PhoneNumber.from_string(phone, region="UZ"), author=operator
    )


def book(operator, ali, *, when=TOMORROW_10, with_lead=True, **kw):
    inv = lead(operator) if with_lead else None
    client = inv.client if inv else None
    if client is None:
        from client.models import Client

        client = Client.objects.get_or_create(phone="+998901119999", defaults={"fio": "Solo"})[0]
    return M.create_metering(
        client=client, date_time=when, invoice=inv, author=operator, measurer=ali, **kw
    )


def upload_file(m, name="a.pdf"):
    from filer.models import File

    f = File(folder=m.folder, original_filename=name)
    f.file.save(name, SimpleUploadedFile(name, PDF))
    return f


# ------------------------------------------------------------------ measurers
def test_measurers_are_explicit_active_staff_only(make_staff, superuser):
    from oauth.models import User

    own = make_staff("oauth.user_metering", name="B own")
    group = Group.objects.create(name="Zamer")
    group.permissions.add(Permission.objects.get(codename="user_metering"))
    via_group = make_staff(name="A group")
    via_group.groups.add(group)
    inactive = make_staff("oauth.user_metering", is_active=False)
    plain = make_staff("metering.view_metering")
    non_staff = User.objects.create_user(phone="+998909990000", password="x", is_staff=False)
    non_staff.user_permissions.add(Permission.objects.get(codename="user_metering"))
    got = list(M.measurers())
    assert got == [via_group, own]  # by name; never the superuser
    assert superuser not in got and inactive not in got and plain not in got
    assert non_staff not in got
    assert M.default_measurer() is None  # two of them


def test_default_measurer_is_the_only_one(ali):
    assert M.default_measurer() == ali


# ------------------------------------------------------------------ create
def test_create_picks_the_only_measurer_and_announces_once(
    operator, ali, bot_events, sms_calls, monkeypatch
):
    from oauth.models import User

    def legacy(*a, **k):
        raise AssertionError("legacy broadcast")

    monkeypatch.setattr(User, "send_messages", classmethod(legacy))
    inv = lead(operator)
    m = M.create_metering(client=inv.client, date_time=TOMORROW_10, invoice=inv, author=operator)
    assert (m.measurer, m.created_by, m.scheduled_at, m.rev) == (ali, operator, NOW, 0)
    data = bot_events.one("metering.assigned")
    assert data["how"] == "new" and data["to"] == [7001]
    brief = data["metering"]
    assert brief["id"] == m.pk and brief["measurer"]["id"] == ali.pk
    assert brief["operator"]["id"] == operator.pk and brief["next_step"] == ""
    assert sms_calls == []  # Telegram is linked: no SMS


def test_create_sms_task_runs_on_commit(make_staff, operator, sms_calls, commit):
    zed = make_staff(*MEASURER_PERMS, name="Zed")
    m = commit(book, operator, zed)
    assert sms_calls == [(m.pk, m.rev)]


def test_create_refusals(make_staff, operator, ali, db_client):
    plain = make_staff("metering.view_metering")
    with pytest.raises(ServiceError) as e:
        M.create_metering(client=db_client, date_time=TOMORROW_10, measurer=plain)
    assert e.value.field == "measurer" and "zamerchi emas" in e.value.message
    make_staff(*MEASURER_PERMS, name="Second")
    with pytest.raises(ServiceError) as e:
        M.create_metering(client=db_client, date_time=TOMORROW_10)
    assert e.value.field == "measurer" and e.value.message == "Zamerchini tanlang"


def test_create_without_any_measurer_books_unassigned(db_client, caplog):
    with caplog.at_level("WARNING", logger="metering"):
        m = M.create_metering(client=db_client, date_time=TOMORROW_10)
    assert m.measurer_id is None and "without a measurer" in caplog.text
    from django.core import checks

    from metering.checks import no_measurer_check

    assert [w.id for w in no_measurer_check(None)] == ["metering.W001"]
    assert isinstance(no_measurer_check(None)[0], checks.Warning)


def test_measurers_endpoint_hints_when_empty(api):
    r = api(*OPERATOR_PERMS).get("/api/v1/meterings/measurers/")
    assert r.status_code == 200 and r.data["items"] == [] and r.data["default"] is None
    assert "user_metering" in r.data["hint"]


def test_unassigned_metering_is_visible_to_a_plain_measurer(api, operator, ali):
    from client.models import Client

    c = Client.objects.create(phone="+998901000099", fio="U")
    m = M.create_metering(client=c, date_time=TOMORROW_10, author=operator, measurer=ali)
    Metering.objects.filter(pk=m.pk).update(measurer=None)
    mine = api(*MEASURER_PERMS)
    assert [r["id"] for r in mine.get("/api/v1/meterings/").data["results"]] == [m.pk]
    assert mine.get(f"/api/v1/meterings/{m.pk}/").status_code == 200


def test_lock_order_invoice_before_metering(operator, ali, monkeypatch):
    from django.db.models.query import QuerySet

    m = book(operator, ali)
    order = []
    orig = QuerySet.select_for_update

    def spy(self, *a, **kw):
        order.append(self.model.__name__)
        return orig(self, *a, **kw)

    monkeypatch.setattr(QuerySet, "select_for_update", spy)
    M.reschedule_metering(m, by=ali, preset="tomorrow")
    assert order[:2] == ["Invoice", "Metering"]
    order.clear()
    M.mark_metering_measured(m, by=ali)
    assert order[:2] == ["Invoice", "Metering"]
    order.clear()
    M.cancel_metering(m, by=ali, reason="uzr bor")
    assert order[:2] == ["Invoice", "Metering"]


def test_cancel_falls_back_when_the_owner_is_inactive(operator, ali, make_staff):
    m = book(operator, ali)
    type(m.invoice).objects.filter(pk=m.invoice_id).update(assigned_to=operator)
    type(operator).objects.filter(pk=operator.pk).update(is_active=False)
    m, returned = M.cancel_metering(m, by=ali, reason="uzr bor")
    assert returned
    task = InvoiceTask.objects.get(invoice=m.invoice)
    assert task.assigned_to_id != operator.pk


def test_cancel_does_not_return_a_lead_that_moved_on(operator, ali):
    m = book(operator, ali)
    type(m.invoice).objects.filter(pk=m.invoice_id).update(solution=SolutionChoice.re_phone)
    m, returned = M.cancel_metering(m, by=ali, reason="uzr bor")
    assert returned is False
    assert not InvoiceTask.objects.filter(invoice=m.invoice).exists()


def test_overdue_bucket_is_limited_to_30_days(operator, ali):
    from client.models import Client

    def mk(when, phone):
        c = Client.objects.create(phone=phone, fio=phone)
        return M.create_metering(client=c, date_time=when, author=operator, measurer=ali)

    recent = mk(NOW - timedelta(days=10), "+998901000011")
    mk(NOW - timedelta(days=40), "+998901000012")
    data = M.metering_agenda(Metering.objects.all(), now=NOW)
    assert [m.pk for m in data["overdue"]] == [recent.pk] and data["counts"]["overdue"] == 1


def test_manager_may_assign_tasks(make_staff):
    from api.serializers.metering import can_assign_tasks

    assert can_assign_tasks(make_staff("metering.manage_metering"))
    assert not can_assign_tasks(make_staff("metering.view_metering"))


def test_files_folder_is_created_lazily(operator, ali):
    m = book(operator, ali)
    Metering.objects.filter(pk=m.pk).update(folder=None)
    m = Metering.objects.get(pk=m.pk)
    rows = M.save_metering_files(m, [SimpleUploadedFile("plan.pdf", PDF)], by=ali)
    assert m.folder_id is not None and rows[0].folder_id == m.folder_id


def test_client_related_and_stats_are_scoped(api, operator, ali):
    m = book(operator, ali)
    Metering.objects.filter(pk=m.pk).update(measurer=operator)
    c = api(*MEASURER_PERMS, "client.view_client")
    r = c.get(f"/api/v1/clients/{m.client_id}/related/")
    assert r.status_code == 200 and r.data["meterings"] == []
    assert c.get("/api/v1/meterings/stats/").data["total"] == 0


def test_second_metering_after_a_cancelled_one(operator, ali):
    inv = lead(operator)
    first = M.create_metering(
        client=inv.client, date_time=TOMORROW_10, invoice=inv, author=operator
    )
    with pytest.raises(ServiceError):  # still open: no second one
        M.create_metering(client=inv.client, date_time=TOMORROW_10, invoice=inv, author=operator)
    M.cancel_metering(first, by=operator, reason="Mijoz o'ylab ko'radi")
    second = M.create_metering(
        client=inv.client, date_time=TOMORROW_10, invoice=inv, author=operator
    )
    first.refresh_from_db()
    assert first.invoice_id is None and second.invoice_id == inv.pk
    inv.refresh_from_db()
    assert inv.solution == SolutionChoice.go_for_measured


# ------------------------------------------------------------------ measured
def test_measured_by_the_measurer(operator, ali, bot_events):
    m = book(operator, ali)
    bot_events.clear()
    M.mark_metering_measured(m, by=ali)
    m.refresh_from_db()
    assert m.status == MeteringStatus.metering_done and m.measured_at == NOW and m.rev == 1
    ev = bot_events.one("metering.changed")
    assert ev["how"] == "measured" and ev["to"] == [7001] and ev["watchers"] == []
    assert ev["by_name"] == "Ali" and ev["metering"]["rev"] == 1
    note = m.invoice.notes.get(kind=NoteKind.metering)
    assert note.meta == {"event": "measured", "metering_id": m.pk}


def test_measured_refusals(operator, ali, boss, make_staff):
    other = make_staff(*MEASURER_PERMS, name="Other")
    m = book(operator, ali)
    with pytest.raises(ServiceForbidden):
        M.mark_metering_measured(m, by=other)
    with pytest.raises(ServiceForbidden):
        M.mark_metering_measured(m, by=operator)  # may change meterings, is not the measurer
    M.mark_metering_measured(m, by=boss)  # the manager may
    with pytest.raises(ServiceConflict):
        M.mark_metering_measured(m, by=ali)
    m.status = MeteringStatus.dont_need
    m.save()
    with pytest.raises(ServiceConflict) as e:
        M.mark_metering_measured(m, by=ali)
    assert "yopilgan" in e.value.message


def test_unassigned_metering_can_be_worked_by_any_measurer(make_staff):
    from client.models import Client

    other = make_staff(*MEASURER_PERMS)
    m = Metering.objects.create(
        client=Client.objects.create(phone="+998901118888", fio="X"), date_time=TOMORROW_10
    )
    assert M.can_work_metering(other, m)
    assert not M.can_work_metering(make_staff("metering.view_metering"), m)


# ------------------------------------------------------------------ reschedule
@pytest.mark.parametrize(
    "now,preset,expected",
    [
        (NOW, "1h", datetime(2026, 11, 3, 13, 0)),
        (NOW + timedelta(minutes=7), "1h", datetime(2026, 11, 3, 13, 30)),
        (NOW + timedelta(minutes=31), "1h", datetime(2026, 11, 3, 14, 0)),
        (NOW, "tomorrow", datetime(2026, 11, 4, 15, 20)),
        (NOW, "2d", datetime(2026, 11, 5, 15, 20)),
    ],
)
def test_reschedule_presets(operator, ali, clock, now, preset, expected):
    m = book(operator, ali, when=datetime(2026, 11, 3, 15, 20))
    clock["v"] = now
    M.reschedule_metering(m, by=ali, preset=preset)
    m.refresh_from_db()
    assert m.date_time == expected and m.status == MeteringStatus.other_day
    assert m.rev == 1 and m.scheduled_at == now


def test_reschedule_text_keeps_the_clock_time(operator, ali):
    m = book(operator, ali, when=datetime(2026, 11, 4, 15, 20))
    M.reschedule_metering(m, by=ali, text="25.12")
    assert m.date_time == datetime(2026, 12, 25, 15, 20)
    M.reschedule_metering(m, by=ali, text="26.12 09:00")
    assert m.date_time == datetime(2026, 12, 26, 9, 0)
    M.reschedule_metering(m, by=ali, text="18:30")
    assert m.date_time == datetime(2026, 11, 3, 18, 30)


def test_reschedule_input_rules(operator, ali):
    m = book(operator, ali)
    for kwargs in (
        {},
        {"preset": "1h", "text": "14:00"},
        {"text": "kecha"},
        {"text": "11:00"},  # already past (now is 12:00)
        {"date_time": NOW - timedelta(hours=1)},
        {"preset": "nope"},
    ):
        with pytest.raises(ServiceError) as e:
            M.reschedule_metering(m, by=ali, **kwargs)
        assert e.value.field == "time", kwargs
    m.refresh_from_db()
    assert m.rev == 0


def test_reschedule_perm_and_timeline_and_watchers(operator, ali, boss, bot_events, make_staff):
    m = book(operator, ali)
    with pytest.raises(ServiceForbidden):
        M.reschedule_metering(m, by=make_staff("metering.view_metering"), preset="1h")
    bot_events.clear()
    M.reschedule_metering(m, by=ali, preset="2d")
    ev = bot_events.one("metering.changed")
    assert ev["how"] == "rescheduled" and ev["to"] == [7001] and ev["watchers"] == [4001]
    note = m.invoice.notes.filter(kind=NoteKind.metering).get()
    assert note.meta["event"] == "rescheduled"
    assert note.meta["from"] == "2026-11-04T10:00:00" and note.meta["to"] == "2026-11-05T10:00:00"
    bot_events.clear()
    M.reschedule_metering(m, by=operator, preset="1h")  # the operator moved it themselves
    ev = bot_events.one("metering.changed")
    assert ev["watchers"] == [] and ev["to"] == [7001]


# ------------------------------------------------------------------ cancel
def test_cancel_returns_the_lead_as_a_call_task(operator, ali, bot_events):
    m = book(operator, ali)
    inv = m.invoice
    bot_events.clear()
    m, returned = M.cancel_metering(m, by=ali, reason="Mijoz o'ylab ko'radi")
    assert returned is True
    inv.refresh_from_db()
    assert inv.solution == SolutionChoice.re_phone
    task = InvoiceTask.objects.get(invoice=inv)
    assert task.text == "Zamer bekor bo'ldi: Mijoz o'ylab ko'radi"
    assert task.due_at == NOW and task.assigned_to == operator and task.done_at is None
    assert m.status == MeteringStatus.dont_need and m.cancelled_at == NOW and m.rev == 1
    ev = bot_events.one("metering.changed")
    assert ev["how"] == "cancelled" and ev["metering"]["cancel_reason"] == "Mijoz o'ylab ko'radi"
    assert inv.notes.filter(kind=NoteKind.metering, meta__event="cancelled").exists()
    # the operator is reminded by the existing task reminder
    bot_events.clear()
    assert CC.due_task_reminders(NOW) == 1
    assert bot_events.one("crm.task_due")["to"] == [4001]


def test_cancel_rules(operator, ali, make_staff):
    m = book(operator, ali)
    for bad in ("", "  ", "ab"):
        with pytest.raises(ServiceError) as e:
            M.cancel_metering(m, by=ali, reason=bad)
        assert e.value.field == "reason"
    with pytest.raises(ServiceForbidden):
        M.cancel_metering(m, by=make_staff("metering.view_metering"), reason="uzr bor")
    M.cancel_metering(m, by=ali, reason="uzr bor")
    with pytest.raises(ServiceConflict):
        M.cancel_metering(m, by=ali, reason="uzr bor")


def test_cancel_without_a_lead_and_after_measuring(operator, ali):
    m = book(operator, ali, with_lead=False)
    M.mark_metering_measured(m, by=ali)
    m, returned = M.cancel_metering(m, by=operator, reason="Bekor qilindi")  # from metering_done
    assert returned is False and m.status == MeteringStatus.dont_need


def test_cancel_leaves_a_sold_lead_alone(operator, ali):
    m = book(operator, ali)
    Metering.objects.filter(pk=m.pk).update()
    type(m.invoice).objects.filter(pk=m.invoice_id).update(solution=SolutionChoice.sold_out)
    m, returned = M.cancel_metering(m, by=ali, reason="uzr bor")
    assert returned is False
    assert not InvoiceTask.objects.filter(invoice=m.invoice).exists()


# ------------------------------------------------------------------ finish
@pytest.fixture
def people(make_staff, default_manager):
    designer = make_staff("oauth.user_design", "design.view_design", name="Dizayner")
    pricer = make_staff("price.change_price", "price.view_price", name="Narxchi")
    return designer, pricer


def test_finish_design_and_price(operator, ali, people, bot_events):
    designer, pricer = people
    m = book(operator, ali)
    M.mark_metering_measured(m, by=ali)
    upload_file(m)
    bot_events.clear()
    out = M.finish_metering(
        m,
        by=ali,
        note="Hammasi o'lchandi",
        next_step="design_price",
        designer=designer,
        pricer=pricer,
    )
    m.refresh_from_db()
    assert out["assigned"] == {"design": "created", "price": "created"}
    assert m.status == MeteringStatus.done and m.done_by == ali and m.done_at == NOW
    assert (m.result_note, m.next_step, m.rev) == ("Hammasi o'lchandi", "design_price", 2)
    ev = bot_events.one("metering.changed")
    assert ev["how"] == "done" and ev["metering"]["next_step"] == "design_price"
    assert m.design.user == designer and m.price.user == pricer
    assert not M.metering_is_editable(m)
    assert m.invoice.notes.get(kind=NoteKind.metering, meta__event="done").text == (
        "Hammasi o'lchandi"
    )
    with pytest.raises(ServiceConflict):
        M.finish_metering(m, by=ali, note="x", next_step="price", pricer=pricer)


def test_finish_only_price(operator, ali, people):
    _, pricer = people
    m = book(operator, ali)
    M.mark_metering_measured(m, by=ali)
    upload_file(m)
    M.finish_metering(m, by=ali, note="ok", next_step="price", pricer=pricer)
    m = Metering.objects.get(pk=m.pk)
    assert m.price.user == pricer and not hasattr(m, "design")


def test_order_can_still_be_created_from_a_done_metering(operator, ali, people, admin_api):
    from metering.design.services import mark_design_done

    designer, pricer = people
    m = book(operator, ali)
    M.mark_metering_measured(m, by=ali)
    upload_file(m)
    M.finish_metering(
        m, by=ali, note="ok", next_step="design_price", designer=designer, pricer=pricer
    )
    m = Metering.objects.get(pk=m.pk)
    design_file(m.design)
    design = mark_design_done(m.design, by=designer)
    type(design).objects.filter(pk=design.pk).update(stage="approved")  # the client said yes
    r = admin_api.post(
        "/api/v1/orders/",
        {
            "metering": m.pk,
            "design_type": design.designtype_set.first().pk,
            "address": "Chilonzor",
            "count_days": 30,
        },
        format="json",
    )
    assert r.status_code == 201, r.content


def test_finish_refusals(operator, ali, people, make_staff):
    designer, pricer = people
    m = book(operator, ali)
    with pytest.raises(ServiceError):  # not measured yet
        M.finish_metering(m, by=ali, note="x", next_step="price", pricer=pricer)
    M.mark_metering_measured(m, by=ali)

    def go(**kw):
        base = dict(by=ali, note="n", next_step="design_price", designer=designer, pricer=pricer)
        return M.finish_metering(m, **{**base, **kw})

    with pytest.raises(ServiceError) as e:
        go()
    assert e.value.field == "files"
    upload_file(m)
    for kw, field in (
        ({"note": "  "}, "note"),
        ({"next_step": "other"}, "next_step"),
        # no pricer: the price goes to the manager, who needs the price rights
        ({"pricer": None}, "manager"),
        ({"next_step": "price"}, "designer"),  # designer is forbidden for price-only
    ):
        with pytest.raises(ServiceError) as e:
            go(**kw)
        assert e.value.field == field, kw
    # one designer is picked by itself; with two the measurer must choose
    make_staff("oauth.user_design", "design.view_design", name="Dizayner 2")
    with pytest.raises(ServiceError) as e:
        go(designer=None)
    assert e.value.field == "designer"
    with pytest.raises(ServiceForbidden):
        go(by=make_staff(*MEASURER_PERMS))
    m.refresh_from_db()
    assert m.status == MeteringStatus.metering_done and m.rev == 1
    assert not hasattr(m, "price")  # nothing half-done


def test_finish_counts_files_in_subfolders(operator, ali, people):
    from filer.models import File, Folder

    _, pricer = people
    m = book(operator, ali)
    M.mark_metering_measured(m, by=ali)
    sub = Folder.objects.create(name="video", parent=m.folder)
    f = File(folder=sub, original_filename="v.pdf")
    f.file.save("v.pdf", SimpleUploadedFile("v.pdf", PDF))
    M.finish_metering(m, by=ali, note="ok", next_step="price", pricer=pricer)
    assert Metering.objects.get(pk=m.pk).status == MeteringStatus.done


# ------------------------------------------------------------------ reassigning
def test_set_measurer(operator, ali, boss, make_staff, bot_events, sms_calls, commit):
    eve = make_staff(*MEASURER_PERMS, name="Eve", telegram_id=7002)
    m = book(operator, ali)
    bot_events.clear()
    with pytest.raises(ServiceForbidden):
        M.set_metering_measurer(m, measurer=eve, by=ali)
    with pytest.raises(ServiceError):
        M.set_metering_measurer(m, measurer=operator, by=boss)
    M.set_metering_measurer(m, measurer=eve, by=boss)
    m.refresh_from_db()
    assert m.measurer == eve and m.rev == 1 and m.scheduled_at == NOW
    changed, assigned = bot_events.one("metering.changed"), bot_events.one("metering.assigned")
    assert changed["how"] == "reassigned" and changed["to"] == [7001]
    assert changed["to_name"] == "Eve"
    assert assigned["how"] == "reassigned" and assigned["to"] == [7002]
    bot_events.clear()
    M.set_metering_measurer(m, measurer=eve, by=boss)  # same person: nothing
    assert bot_events == [] and Metering.objects.get(pk=m.pk).rev == 1


# ------------------------------------------------------------------ files
def test_save_metering_files(operator, ali, make_staff):
    m = book(operator, ali)
    rows = M.save_metering_files(m, [SimpleUploadedFile("plan.pdf", PDF)], by=ali)
    assert len(rows) == 1 and rows[0].folder_id == m.folder_id and rows[0].owner == ali
    with pytest.raises(ServiceForbidden):
        M.save_metering_files(m, [SimpleUploadedFile("p.pdf", PDF)], by=make_staff())
    with pytest.raises(ServiceError) as e:  # extension not allowed
        M.save_metering_files(m, [SimpleUploadedFile("x.exe", b"MZ")], by=ali)
    assert "x.exe" in e.value.message
    big = SimpleUploadedFile("big.mp4", b"x")
    big.size = 501 * 1024 * 1024
    with pytest.raises(ServiceError) as e:
        M.save_metering_files(m, [big], by=ali)
    assert e.value.field == "files" and "500 MB" in e.value.message
    video = M.save_metering_files(m, [SimpleUploadedFile("c.webm", b"\x1aE\xdf\xa3")], by=ali)
    assert video[0].original_filename == "c.webm"
    M.cancel_metering(m, by=ali, reason="uzr bor")
    with pytest.raises(ServiceError):
        M.save_metering_files(m, [SimpleUploadedFile("p.pdf", PDF)], by=ali)


# ------------------------------------------------------------------ reminders
def test_soon_and_late_reminders_fire_once_per_revision(operator, ali, bot_events, clock):
    m = book(operator, ali, when=datetime(2026, 11, 3, 15, 0))  # told at 12:00, 3 h ahead
    bot_events.clear()
    assert M.due_metering_reminders(datetime(2026, 11, 3, 13, 59)) == {
        "soon": 0,
        "late": 0,
        "digest": 0,
    }
    assert M.due_metering_reminders(datetime(2026, 11, 3, 14, 0))["soon"] == 1
    assert M.due_metering_reminders(datetime(2026, 11, 3, 14, 30))["soon"] == 0  # once
    ev = bot_events.one("metering.reminder")
    assert ev["kind"] == "soon" and ev["to"] == [7001] and ev["metering"]["id"] == m.pk
    # no answer an hour after the time: one nudge
    assert M.due_metering_reminders(datetime(2026, 11, 3, 16, 0))["late"] == 1
    assert M.due_metering_reminders(datetime(2026, 11, 3, 16, 30))["late"] == 0
    # moving the time is a new revision: both reminders can fire again
    clock["v"] = datetime(2026, 11, 3, 16, 5)
    M.reschedule_metering(m, by=ali, text="20:00")
    assert M.due_metering_reminders(datetime(2026, 11, 3, 19, 0))["soon"] == 1


def test_no_nudge_when_told_less_than_an_hour_ahead(operator, ali):
    book(operator, ali, when=datetime(2026, 11, 3, 12, 40))  # told at 12:00
    assert M.due_metering_reminders(datetime(2026, 11, 3, 12, 10))["soon"] == 0


def test_reminders_skip_closed_unreachable_and_old(operator, ali, make_staff, bot_events):
    quiet = make_staff(*MEASURER_PERMS, name="Quiet")  # no Telegram
    a = book(operator, ali, when=datetime(2026, 11, 3, 15, 0))
    b = book(operator, quiet, when=datetime(2026, 11, 3, 15, 0))
    Metering.objects.filter(pk=b.pk).update(scheduled_at=NOW)
    book(operator, ali, when=datetime(2026, 11, 1, 10, 0))  # two days late: outside 24 h
    bot_events.clear()
    M.mark_metering_measured(a, by=ali)
    bot_events.clear()
    sent = M.due_metering_reminders(datetime(2026, 11, 3, 14, 30))
    assert sent["soon"] == 0 and bot_events.of("metering.reminder") == []
    assert (
        M.due_metering_reminders(datetime(2026, 11, 3, 17, 0))["late"] == 0
    )  # a measured, b quiet


def test_digest_once_per_measurer_per_day(operator, ali, make_staff, bot_events):
    eve = make_staff(*MEASURER_PERMS, name="Eve", telegram_id=7002)
    book(operator, ali, when=datetime(2026, 11, 4, 15, 0))
    book(operator, ali, when=datetime(2026, 11, 4, 9, 0))
    book(operator, eve, when=datetime(2026, 11, 5, 9, 0))  # the day after: not tomorrow
    bot_events.clear()
    assert M.due_metering_reminders(datetime(2026, 11, 3, 19, 59))["digest"] == 0
    assert M.due_metering_reminders(datetime(2026, 11, 3, 20, 0))["digest"] == 1
    assert M.due_metering_reminders(datetime(2026, 11, 3, 21, 0))["digest"] == 0
    ev = bot_events.one("metering.digest")
    assert ev["to"] == [7001] and ev["date"] == "2026-11-04"
    assert [i["date_time"][11:16] for i in ev["items"]] == ["09:00", "15:00"]
    assert ev["url"].endswith("/meterings?tab=tomorrow")


def test_assignment_sms_task(make_staff, operator, monkeypatch):
    from metering import tasks

    sent = []
    monkeypatch.setattr("core.sms.send_bulk_sms", lambda msgs: sent.extend(msgs))
    zed = make_staff(*MEASURER_PERMS, name="Zed")
    m = book(operator, zed)
    assert tasks.assignment_sms(m.pk, m.rev) is True
    assert tasks.assignment_sms(m.pk, m.rev) is False  # once
    assert tasks.assignment_sms(m.pk, m.rev + 1) is False  # stale revision
    assert "Zed" in sent[0]["text"] and f"/meterings/{m.pk}" in sent[0]["text"]
    ali2 = make_staff(*MEASURER_PERMS, telegram_id=9)
    m2 = book(operator, ali2)
    assert tasks.assignment_sms(m2.pk, m2.rev) is False  # has Telegram


def test_schedule_syncs_the_zamer_task(db):
    from django_celery_beat.models import PeriodicTask

    from accounting.schedule import sync_periodic_tasks

    sync_periodic_tasks()
    pt = PeriodicTask.objects.get(name="zamer: eslatmalar")
    assert pt.task == "metering.tasks.metering_reminders" and pt.crontab.minute == "*"


# ------------------------------------------------------------------ agenda / scoping
def test_agenda_buckets(operator, ali):
    def mk(when, phone):
        from client.models import Client

        c = Client.objects.create(phone=phone, fio=phone)
        return M.create_metering(client=c, date_time=when, author=operator, measurer=ali)

    overdue = mk(datetime(2026, 11, 3, 10, 30), "+998901000001")  # 90 min late
    just_now = mk(datetime(2026, 11, 3, 11, 30), "+998901000002")  # 30 min late: still "today"
    today = mk(datetime(2026, 11, 3, 18, 0), "+998901000003")
    tomorrow = mk(datetime(2026, 11, 4, 9, 0), "+998901000004")
    week = mk(datetime(2026, 11, 8, 9, 0), "+998901000005")
    far = mk(datetime(2026, 11, 20, 9, 0), "+998901000006")
    waiting = mk(datetime(2026, 11, 3, 9, 0), "+998901000007")
    M.mark_metering_measured(waiting, by=ali)
    gone = mk(datetime(2026, 11, 3, 18, 0), "+998901000008")
    M.cancel_metering(gone, by=ali, reason="uzr bor")
    data = M.metering_agenda(Metering.objects.all(), now=NOW)
    ids = lambda key: [m.pk for m in data[key]]  # noqa: E731
    assert ids("overdue") == [overdue.pk]
    assert ids("today") == [just_now.pk, today.pk]
    assert ids("tomorrow") == [tomorrow.pk]
    assert ids("week") == [just_now.pk, today.pk, tomorrow.pk, week.pk]
    assert ids("waiting") == [waiting.pk]
    assert data["counts"] == {
        "overdue": 1,
        "today": 2,
        "tomorrow": 1,
        "week": 4,
        "waiting": 1,
        "archive": 1,
    }
    assert far.pk not in ids("week")
    assert M.is_overdue(overdue, NOW) and not M.is_overdue(just_now, NOW)


def test_api_scoping_and_agenda(api, operator, ali, boss, make_staff, db_client):
    m = book(operator, ali)
    other = make_staff(*MEASURER_PERMS, name="Other")
    mine = api(*MEASURER_PERMS)
    mine.user.user_permissions.clear()
    # a measurer sees only their own rows
    c_ali = api(*MEASURER_PERMS, telegram_id=7777)
    Metering.objects.filter(pk=m.pk).update(measurer=c_ali.user)
    assert [r["id"] for r in c_ali.get("/api/v1/meterings/").data["results"]] == [m.pk]
    assert c_ali.get(f"/api/v1/meterings/{m.pk}/").status_code == 200
    Metering.objects.filter(pk=m.pk).update(measurer=other)
    assert c_ali.get(f"/api/v1/meterings/{m.pk}/").status_code == 404
    assert c_ali.get("/api/v1/meterings/").data["results"] == []
    assert c_ali.post(f"/api/v1/meterings/{m.pk}/metering-done/").status_code == 404
    # a manager sees all and can filter
    c_boss = api(*MEASURER_PERMS, "metering.manage_metering")
    assert len(c_boss.get("/api/v1/meterings/").data["results"]) == 1
    assert c_boss.get(f"/api/v1/meterings/?measurer={other.pk}").data["count"] == 1
    assert c_boss.get(f"/api/v1/meterings/?measurer={ali.pk}").data["count"] == 0
    assert c_boss.get("/api/v1/meterings/?measurer=me").data["count"] == 0
    agenda = c_boss.get("/api/v1/meterings/agenda/").data
    assert set(agenda) == {"counts", "overdue", "today", "tomorrow", "week", "waiting"}
    assert set(agenda["counts"]) == {"overdue", "today", "tomorrow", "week", "waiting", "archive"}
    assert agenda["counts"]["tomorrow"] == 1 and agenda["tomorrow"][0]["id"] == m.pk
    assert c_boss.get("/api/v1/meterings/agenda/?search=zzz").data["counts"]["tomorrow"] == 0
    assert c_ali.get("/api/v1/meterings/agenda/").data["counts"]["tomorrow"] == 0


def test_api_actions_and_validation(api, operator, ali, people):
    designer, pricer = people
    c_op = api(*OPERATOR_PERMS, telegram_id=4010)
    body = {
        "client_phone": "+998901117777",
        "client_fio": "Yangi",
        "date_time": "2026-11-05T10:00:00",
        "address": "Chilonzor",
    }
    # only the admin books a zamer without a lead
    r = c_op.post("/api/v1/meterings/", body, format="json")
    assert r.status_code == 400 and r.data["field"] == "invoice"
    body["invoice"] = lead(operator, body["client_phone"]).pk
    r = c_op.post("/api/v1/meterings/", body, format="json")
    assert r.status_code == 201, r.content
    assert r.data["measurer"]["id"] == ali.pk and r.data["operator"]["id"] == c_op.user.pk
    mid = r.data["id"]
    url = f"/api/v1/meterings/{mid}"
    # PATCH no longer changes the time
    r = c_op.patch(f"{url}/", {"date_time": "2030-01-01T10:00:00", "desc": "yangi"}, format="json")
    assert r.status_code == 200 and r.data["desc"] == "yangi"
    assert r.data["date_time"].startswith("2026-11-05T10:00")
    # other-day needs a time, dont-need a reason
    assert c_op.post(f"{url}/other-day/", {}, format="json").status_code == 400
    assert c_op.post(f"{url}/dont-need/", {}, format="json").status_code == 400
    r = c_op.post(f"{url}/other-day/", {"date_time": "2026-11-06T11:00:00"}, format="json")
    assert r.status_code == 200 and r.data["status"] == "other_day" and r.data["rev"] == 1
    acts = r.data["actions"]
    assert acts["reschedule"] and acts["cancel"] and acts["upload"] and not acts["finish"]
    assert acts["measured"] is False  # the operator is not the measurer
    c_ali = api(*MEASURER_PERMS)
    Metering.objects.filter(pk=mid).update(measurer=c_ali.user)
    r = c_ali.post(f"{url}/metering-done/")
    assert r.status_code == 200 and r.data["status"] == "metering_done"
    assert r.data["actions"]["finish"] is True and r.data["actions"]["measured"] is False
    # files: multipart, one per request
    r = c_ali.post(f"{url}/files/", {"file": SimpleUploadedFile("a.pdf", PDF)}, format="multipart")
    assert r.status_code == 201 and r.data[0]["name"] == "a.pdf"
    assert len(c_ali.get(f"{url}/files/").data) == 1
    assert c_ali.get(f"{url}/").data["file_count"] == 1
    assert c_ali.post(f"{url}/files/", {}, format="multipart").status_code == 400
    r = c_ali.post(f"{url}/finish/", {"note": "ok", "next_step": "price"}, format="json")
    # no pricer: the manager calculates the price, and this one has no price rights
    assert r.status_code == 400 and r.data["field"] == "manager"
    r = c_ali.post(
        f"{url}/finish/", {"note": "ok", "next_step": "price", "pricer": pricer.pk}, format="json"
    )
    assert r.status_code == 200, r.content
    assert r.data["status"] == "done" and r.data["assigned"]["price"] == "created"
    assert r.data["next_step"] == "price" and r.data["actions"]["finish"] is False


def test_api_cancel_reports_lead_return(api, operator, ali):
    m = book(operator, ali)
    c = api(*OPERATOR_PERMS)
    r = c.post(f"/api/v1/meterings/{m.pk}/dont-need/", {"reason": "uzr bor"}, format="json")
    assert r.status_code == 200 and r.data["lead_returned"] is True
    assert r.data["cancel_reason"] == "uzr bor" and r.data["status"] == "dont_need"
    r = c.post(f"/api/v1/meterings/{m.pk}/dont-need/", {"reason": "uzr bor"}, format="json")
    assert r.status_code == 400  # already cancelled (a 400 on the site)


def test_api_measurers_and_set_measurer(api, operator, ali, make_staff):
    eve = make_staff(*MEASURER_PERMS, name="Eve")
    c = api(*OPERATOR_PERMS)
    r = c.get("/api/v1/meterings/measurers/")
    assert r.status_code == 200 and r.data["default"] is None
    assert {u["id"] for u in r.data["items"]} == {ali.pk, eve.pk}
    assert api("metering.view_metering").get("/api/v1/meterings/measurers/").status_code == 403
    m = book(operator, ali)
    r = c.post(f"/api/v1/meterings/{m.pk}/measurer/", {"measurer": eve.pk}, format="json")
    assert r.status_code == 200 and r.data["measurer"]["id"] == eve.pk
    assert (
        c.post(
            f"/api/v1/meterings/{m.pk}/measurer/", {"measurer": 99999}, format="json"
        ).status_code
        == 404
    )
    r = c.post(
        "/api/v1/meterings/",
        {
            "client_phone": "+998901117776",
            "client_fio": "Z",
            "date_time": "2026-11-05T10:00:00",
            "invoice": lead(operator, "+998901117776").pk,
        },
        format="json",
    )
    assert r.status_code == 400 and r.data["field"] == "measurer"


def test_invoice_serializer_exposes_the_metering_with_stable_queries(
    api, operator, ali, django_assert_max_num_queries
):
    for i in range(4):
        inv = lead(operator, phone=f"+99890111{i:04d}")
        M.create_metering(client=inv.client, date_time=TOMORROW_10, invoice=inv, author=operator)
    c = api(*OPERATOR_PERMS)
    r = c.get("/api/v1/invoices/")
    assert r.status_code == 200
    got = [row["metering"] for row in r.data["results"]]
    assert all(g["measurer"]["id"] == ali.pk and g["status"] == "created" for g in got)
    assert set(got[0]) == {
        "id",
        "status",
        "status_label",
        "date_time",
        "measurer",
        "result_note",
        "cancel_reason",
        "next_step",
        "folder",
        "manager",
        "client_result",
        "design",
        "price",
    }
    with django_assert_max_num_queries(15):
        c.get("/api/v1/invoices/")


# ------------------------------------------------------------------ edge cases (gaps)
def test_reminder_window_boundaries(operator, ali, bot_events):
    """soon: now < time <= now + 60 min; late: now - 24 h <= time <= now - 60 min."""
    m = book(operator, ali, when=datetime(2026, 11, 3, 18, 0))
    Metering.objects.filter(pk=m.pk).update(scheduled_at=NOW)
    assert M.due_metering_reminders(datetime(2026, 11, 3, 16, 59))["soon"] == 0  # 61 min ahead
    assert M.due_metering_reminders(datetime(2026, 11, 3, 17, 0))["soon"] == 1  # exactly 60
    n = book(operator, ali, when=datetime(2026, 11, 3, 18, 0), with_lead=False)
    Metering.objects.filter(pk=n.pk).update(scheduled_at=NOW)
    assert M.due_metering_reminders(datetime(2026, 11, 3, 18, 0))["soon"] == 0  # time == now
    assert M.due_metering_reminders(datetime(2026, 11, 3, 18, 59))["late"] == 0  # 59 min late
    assert M.due_metering_reminders(datetime(2026, 11, 3, 19, 0))["late"] == 2  # exactly 60, m + n
    old = book(operator, ali, when=datetime(2026, 11, 2, 12, 0), with_lead=False)
    Metering.objects.filter(pk=old.pk).update(scheduled_at=datetime(2026, 11, 1))
    assert M.due_metering_reminders(datetime(2026, 11, 3, 12, 0))["late"] == 1  # exactly 24 h
    old2 = book(operator, ali, when=datetime(2026, 11, 2, 11, 59), with_lead=False)
    Metering.objects.filter(pk=old2.pk).update(scheduled_at=datetime(2026, 11, 1))
    assert M.due_metering_reminders(datetime(2026, 11, 3, 12, 0))["late"] == 0  # 24 h + 1 min


def test_reminders_cover_other_day_but_not_measured_waiting(operator, ali, bot_events, clock):
    m = book(operator, ali, when=datetime(2026, 11, 3, 15, 0))
    clock["v"] = datetime(2026, 11, 3, 12, 30)
    M.reschedule_metering(m, by=ali, date_time=datetime(2026, 11, 3, 18, 0))
    m.refresh_from_db()
    assert m.status == MeteringStatus.other_day
    assert M.due_metering_reminders(datetime(2026, 11, 3, 17, 30))["soon"] == 1
    M.mark_metering_measured(m, by=ali)
    bot_events.clear()
    assert M.due_metering_reminders(datetime(2026, 11, 3, 20, 0)) == {
        "soon": 0,
        "late": 0,
        "digest": 0,
    }
    assert bot_events.of("metering.reminder") == []


def test_digest_skips_closed_unreachable_and_inactive(operator, ali, make_staff, bot_events):
    noTg = make_staff(*MEASURER_PERMS, name="NoTg")
    gone = make_staff(*MEASURER_PERMS, name="Gone", telegram_id=7003)
    done_one = book(operator, ali, when=datetime(2026, 11, 4, 9, 0), with_lead=False)
    book(operator, noTg, when=datetime(2026, 11, 4, 10, 0), with_lead=False)
    book(operator, gone, when=datetime(2026, 11, 4, 11, 0), with_lead=False)
    gone.is_active = False
    gone.save(update_fields=["is_active"])
    M.cancel_metering(done_one, by=ali, reason="Mijoz yo'q")  # ali's only one tomorrow is gone
    bot_events.clear()
    assert M.due_metering_reminders(datetime(2026, 11, 3, 21, 0))["digest"] == 0
    assert bot_events.of("metering.digest") == []


def test_cancel_through_the_api_reminds_the_operator(api, operator, ali, bot_events):
    m = book(operator, ali)
    c = api(*MEASURER_PERMS, telegram_id=7010)
    Metering.objects.filter(pk=m.pk).update(measurer=c.user)
    r = c.post(f"/api/v1/meterings/{m.pk}/dont-need/", {"reason": "Mijoz rad etdi"}, format="json")
    assert r.status_code == 200 and r.data["lead_returned"] is True
    bot_events.clear()
    assert CC.due_task_reminders(NOW) == 1
    assert bot_events.one("crm.task_due")["to"] == [4001]
    assert CC.due_task_reminders(NOW) == 0  # once


def test_api_scoping_unknown_actions_all_404(api, operator, ali, make_staff):
    m = book(operator, ali)
    stranger = api(*MEASURER_PERMS)  # a measurer, but not this zamer's
    base = f"/api/v1/meterings/{m.pk}"
    assert stranger.get(f"{base}/files/").status_code == 404
    assert (
        stranger.post(
            f"{base}/other-day/", {"date_time": "2026-11-09T10:00"}, format="json"
        ).status_code
        == 404
    )
    assert stranger.post(f"{base}/dont-need/", {"reason": "abc"}, format="json").status_code == 404
    assert stranger.post(f"{base}/finish/", {}, format="json").status_code == 404
    assert (
        stranger.post(f"{base}/measurer/", {"measurer": ali.pk}, format="json").status_code == 404
    )


def test_agenda_and_list_query_count_does_not_grow(api, operator, ali):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    boss = api(*MEASURER_PERMS, "metering.manage_metering")

    def counts():
        out = []
        for url in ("/api/v1/meterings/agenda/", "/api/v1/meterings/"):
            with CaptureQueriesContext(connection) as q:
                assert boss.get(url).status_code == 200
            out.append(len(q))
        return out

    for i in range(2):
        book(operator, ali, when=TOMORROW_10 + timedelta(hours=i), with_lead=(i % 2 == 0))
    counts()  # warm the permission / constance / content-type caches
    few = counts()
    for i in range(2, 10):
        book(operator, ali, when=TOMORROW_10 + timedelta(hours=i), with_lead=(i % 2 == 0))
    many = counts()
    assert many == few, f"queries grow with rows: {few} -> {many}"


def test_users_page_toggles_measurer_and_manager(admin_api, make_staff):
    from metering.services import measurers
    from oauth.models import User

    u = make_staff("metering.view_metering")
    r = set_levels(u, {"metering_measurer": "view", "metering_manager": "view"})
    assert r.status_code == 200, r.data
    fresh = User.objects.get(pk=u.pk)
    assert fresh.has_perm("oauth.user_metering") and fresh.has_perm("metering.manage_metering")
    assert u.pk in set(measurers().values_list("pk", flat=True))
    flags = {
        s["key"]: s["is_flag"]
        for s in admin_api.get(f"/api/v1/users/{u.pk}/access/").data["sections"]
    }
    assert flags["metering_measurer"] and flags["metering_manager"] and not flags["meterings"]
    set_levels(u, {"metering_measurer": "none"})
    assert not User.objects.get(pk=u.pk).has_perm("oauth.user_metering")
