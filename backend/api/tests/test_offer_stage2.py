"""Zamer stage 2: design and price (docs/BOT_CONTRACT.md, "Dizayn va narx")."""

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
from metering.constants import ClientResult, MeteringStatus
from metering.design import services as DS
from metering.models import Metering, OfferAnswer
from metering.price import services as PS

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 11, 3, 12, 0)  # a Tuesday
WHEN = datetime(2026, 11, 4, 10, 0)
PDF = b"%PDF-1.4\n%test\n"


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    now = {"v": NOW}
    monkeypatch.setattr(M, "_now", lambda: now["v"])
    monkeypatch.setattr(CC, "_now", lambda: now["v"])
    monkeypatch.setattr("metering.tasks.assignment_sms.delay", lambda *a: None)
    return now


@pytest.fixture
def commit(django_capture_on_commit_callbacks):
    def _run(fn, *args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return fn(*args, **kwargs)

    return _run


@pytest.fixture
def ali(make_staff):
    return make_staff("oauth.user_metering", "metering.view_metering", name="Ali", telegram_id=7001)


@pytest.fixture
def operator(make_staff):
    return make_staff(
        "call_center.view_invoice",
        "call_center.add_invoice",
        "call_center.change_invoice",
        "metering.view_metering",
        "metering.change_metering",
        name="Dilfuza",
        telegram_id=4001,
    )


@pytest.fixture
def designer(make_staff):
    return make_staff(
        "oauth.user_design", "design.view_design", "design.change_design",
        name="Dizayner", telegram_id=9001,
    )  # fmt: skip


@pytest.fixture
def pricer(make_staff):
    return make_staff("price.change_price", "price.view_price", name="Narxchi", telegram_id=9002)


@pytest.fixture
def manager(make_staff):
    return make_staff(
        "metering.present_to_client",
        "metering.view_metering",
        "design.view_design",
        "price.view_price",
        name="Menejer",
        telegram_id=9003,
    )


def lead(operator, phone="+998901112233"):
    return CC.create_invoice(
        fio="Karim", phone=PhoneNumber.from_string(phone, region="UZ"), author=operator
    )


def upload_file(m, name="a.pdf"):
    from filer.models import File

    f = File(folder=m.folder, original_filename=name)
    f.file.save(name, SimpleUploadedFile(name, PDF))
    return f


def finished(operator, ali, designer, pricer, manager, step="design_price", **kw):
    inv = lead(operator)
    m = M.create_metering(
        client=inv.client, date_time=WHEN, invoice=inv, author=operator, measurer=ali
    )
    M.mark_metering_measured(m, by=ali)
    upload_file(m)
    M.finish_metering(
        m,
        by=ali,
        note="Hammasi o'lchandi",
        next_step=step,
        designer=designer if step == "design_price" else None,
        pricer=pricer,
        manager=manager,
        **kw,
    )
    return Metering.objects.get(pk=m.pk)


@pytest.fixture
def flow(operator, ali, designer, pricer, manager):
    """A finished design + price metering: both in work."""
    return finished(operator, ali, designer, pricer, manager)


def quiet_price(flow):
    """The price runs next to the design now: park it so a test counts one task's reminders."""
    from metering.price.models import Price

    Price.objects.filter(metering=flow).update(stage="cancelled")


def ready_design(flow, designer):
    design_file(flow.design)
    DS.mark_design_done(flow.design, by=designer)
    return Metering.objects.get(pk=flow.pk)


# ------------------------------------------------------------------ regression
def test_creating_a_design_makes_the_first_variant(db_client):
    """Regression: two receivers shared one name; creating a Design must give the first
    variant «Дизайн-1» and its Filer folder."""
    from metering.design.models import Design, DesignType

    m = Metering.objects.create(client=db_client)
    d = Design.objects.create(metering=m)
    types = list(DesignType.objects.filter(design=d))
    assert [t.name for t in types] == ["Дизайн-1"]
    assert types[0].folder_id is not None
    # and exactly one, also through the service
    d2 = DS.create_design(Metering.objects.create(client=db_client), user=None, due_at=NOW)
    assert d2.designtype_set.count() == 1


# ------------------------------------------------------------------ people
def test_managers_are_explicit_active_staff_only(make_staff, superuser):
    own = make_staff("metering.present_to_client", name="B own")
    group = Group.objects.create(name="Menejerlar")
    group.permissions.add(Permission.objects.get(codename="present_to_client"))
    via_group = make_staff(name="A group")
    via_group.groups.add(group)
    inactive = make_staff("metering.present_to_client", is_active=False)
    plain = make_staff("metering.view_metering")
    got = list(M.managers())
    assert got == [via_group, own]
    assert superuser not in got and inactive not in got and plain not in got
    assert M.default_manager() is None  # two of them


def test_default_manager_is_the_only_one(manager):
    assert M.default_manager() == manager


def test_order_creators_are_explicit_holders(make_staff, superuser):
    maker = make_staff("order.add_order")
    make_staff("order.view_order")
    assert list(M.order_creators()) == [maker]


# ------------------------------------------------------------------ deadlines
def test_default_due_and_shift_due():
    assert M.default_due(2, now=NOW) == datetime(2026, 11, 5, 18, 0)
    d = M.offer_defaults(NOW)
    assert d == {
        "design_due_at": datetime(2026, 11, 5, 18, 0),
        "price_due_at": datetime(2026, 11, 4, 18, 0),
    }
    cur = datetime(2026, 11, 5, 15, 30)
    assert M.shift_due(cur, now=NOW, preset="1d") == datetime(2026, 11, 6, 15, 30)
    assert M.shift_due(cur, now=NOW, preset="3d") == datetime(2026, 11, 8, 15, 30)
    # an overdue deadline counts from today
    old = datetime(2026, 10, 1, 9, 0)
    assert M.shift_due(old, now=NOW, preset="2d") == datetime(2026, 11, 5, 9, 0)
    assert M.shift_due(cur, now=NOW, text="25.12") == datetime(2026, 12, 25, 15, 30)
    assert M.shift_due(cur, now=NOW, text="25.12 09:00") == datetime(2026, 12, 25, 9, 0)
    assert M.shift_due(None, now=NOW, preset="1d") == datetime(2026, 11, 4, 18, 0)
    for kw in ({}, {"preset": "1d", "text": "14:00"}, {"preset": "9y"}, {"text": "zzz"}):
        with pytest.raises(ServiceError) as e:
            M.shift_due(cur, now=NOW, **kw)
        assert e.value.field == "due", kw
    with pytest.raises(ServiceError) as e:
        M.shift_due(cur, now=NOW, due_at=NOW)  # not in the future
    assert e.value.field == "due"


# ------------------------------------------------------------------ finish
def book_measured(operator, ali):
    inv = lead(operator)
    m = M.create_metering(
        client=inv.client, date_time=WHEN, invoice=inv, author=operator, measurer=ali
    )
    M.mark_metering_measured(m, by=ali)
    upload_file(m)
    return m


def test_finish_design_price_defaults_and_events(
    operator, ali, designer, pricer, manager, bot_events
):
    m = book_measured(operator, ali)
    bot_events.clear()
    out = M.finish_metering(
        m, by=ali, note="n", next_step="design_price", designer=designer, pricer=pricer
    )  # the only manager is preselected
    m = Metering.objects.get(pk=m.pk)
    assert out["assigned"] == {"design": "created", "price": "created"}
    assert m.manager == manager
    d, p = m.design, m.price
    assert (d.stage, d.due_at, d.user) == ("work", datetime(2026, 11, 5, 18, 0), designer)
    assert d.assigned_at == NOW and d.round == 1 and d.designtype_set.count() == 1
    # design and price start together: each has its deadline, both people are told
    assert (p.stage, p.due_at, p.user) == ("work", datetime(2026, 11, 4, 18, 0), pricer)
    ev = {e["task"]["kind"]: e for e in bot_events.of("offer.assigned")}
    assert ev["design"]["to"] == [9001] and ev["design"]["how"] == "new"
    assert ev["price"]["to"] == [9002] and ev["price"]["how"] == "new"
    assert (
        ev["design"]["task"]["due_at"] == "2026-11-05T18:00:00"
        and ev["design"]["task"]["manager"]["id"] == manager.pk
        and ev["price"]["task"]["due_at"] == "2026-11-04T18:00:00"
    )
    assert bot_events.of("offer.reminder") == []


def test_finish_price_only_starts_the_price(operator, ali, pricer, manager, bot_events):
    bot_events.clear()
    m = finished(operator, ali, None, pricer, manager, step="price")
    assert not hasattr(m, "design")
    p = m.price
    assert (p.stage, p.due_at) == ("work", datetime(2026, 11, 4, 18, 0))
    ev = bot_events.one("offer.assigned")
    assert ev["to"] == [9002] and ev["task"]["kind"] == "price"


def test_finish_custom_deadlines(operator, ali, designer, pricer, manager):
    due = datetime(2026, 11, 9, 12, 0)
    pdue = datetime(2026, 11, 10, 15, 0)
    m = finished(operator, ali, designer, pricer, manager, design_due_at=due, price_due_at=pdue)
    assert m.design.due_at == due and m.price.due_at == pdue
    m2 = finished(operator, ali, None, pricer, manager, step="price", price_due_at=due)
    assert m2.price.due_at == due


def test_finish_manager_rules(operator, ali, designer, pricer, make_staff):
    m = book_measured(operator, ali)

    def go(**kw):
        base = dict(by=ali, note="n", next_step="design_price", designer=designer, pricer=pricer)
        return M.finish_metering(m, **{**base, **kw})

    boss1 = make_staff("metering.present_to_client")
    make_staff("metering.present_to_client")
    with pytest.raises(ServiceError) as e:  # two of them: choose
        go()
    assert e.value.field == "manager"
    with pytest.raises(ServiceError) as e:
        go(manager=designer)
    assert e.value.field == "manager" and "menejer emas" in e.value.message
    m.refresh_from_db()
    assert m.status == MeteringStatus.metering_done  # nothing half-done
    go(manager=boss1)
    assert Metering.objects.get(pk=m.pk).manager == boss1


def test_finish_deadline_validation(operator, ali, designer, pricer, manager):
    m = book_measured(operator, ali)

    def go(**kw):
        base = dict(
            by=ali, note="n", next_step="design_price", designer=designer, pricer=pricer,
            manager=manager,
        )  # fmt: skip
        return M.finish_metering(m, **{**base, **kw})

    with pytest.raises(ServiceError) as e:
        go(design_due_at=NOW)
    assert e.value.field == "design_due"
    with pytest.raises(ServiceError) as e:  # the price deadline is checked with the design
        go(price_due_at=NOW - timedelta(hours=1))
    assert e.value.field == "price_due"
    with pytest.raises(ServiceError) as e:
        go(next_step="price", designer=None, price_due_at=NOW - timedelta(days=1))
    assert e.value.field == "price_due"
    assert Metering.objects.get(pk=m.pk).status == MeteringStatus.metering_done
    go(price_due_at=NOW + timedelta(days=30))


def test_finish_sms_only_without_telegram(
    operator, ali, designer, pricer, manager, commit, monkeypatch
):
    sent = []
    monkeypatch.setattr("metering.tasks.offer_sms.delay", lambda *a: sent.append(a))
    commit(finished, operator, ali, designer, pricer, manager)
    assert sent == []  # designer has Telegram
    designer.telegram_id = None
    designer.save()
    m = commit(finished, operator, ali, designer, pricer, manager)
    assert sent == [("design", m.design.pk, m.design.rev, "assigned")]


def test_no_legacy_messages(operator, ali, designer, pricer, manager, monkeypatch):
    from oauth.models import User

    def boom(*a, **k):
        raise AssertionError("legacy send")

    monkeypatch.setattr(User, "send_message", boom)
    monkeypatch.setattr(User, "send_messages", classmethod(boom))
    monkeypatch.setattr("oauth.services.notify_user", boom)
    m = finished(operator, ali, designer, pricer, manager)
    ready_design(m, designer)


# ------------------------------------------------------------------ assign / reassign
def test_assign_reassigns_with_events(flow, make_staff, bot_events, designer):
    other = make_staff("oauth.user_design", "design.view_design", name="Boshqa", telegram_id=9010)
    bot_events.clear()
    out = M.assign_metering_tasks(flow, designer=other)
    assert out == {"design": "reassigned", "price": None}
    old = bot_events.one("offer.changed")
    assert old["how"] == "reassigned" and old["to"] == [9001] and old["to_name"] == "Boshqa"
    new = bot_events.one("offer.assigned")
    assert new["how"] == "reassigned" and new["to"] == [9010]
    d = Metering.objects.get(pk=flow.pk).design
    assert d.user == other and d.rev == 1


def test_reassign_a_price_in_work_tells_both(flow, make_staff, bot_events):
    other = make_staff("price.change_price", "price.view_price", name="Yangi", telegram_id=9011)
    bot_events.clear()
    M.assign_metering_tasks(flow, pricer=other)
    new = bot_events.one("offer.assigned")
    assert new["how"] == "reassigned" and new["to"] == [9011]
    assert Metering.objects.get(pk=flow.pk).price.user == other


def test_assign_refuses_a_closed_task(flow, designer, make_staff):
    ready_design(flow, designer)
    other = make_staff("oauth.user_design", "design.view_design")
    with pytest.raises(ServiceError):
        M.assign_metering_tasks(flow, designer=other)


# ------------------------------------------------------------------ mark done
def test_design_done_rules_and_events(flow, designer, make_staff, manager, bot_events):
    d = flow.design
    stranger = make_staff("design.change_design", "design.view_design")
    with pytest.raises(ServiceForbidden):
        DS.mark_design_done(d, by=stranger)
    with pytest.raises(ServiceError) as e:  # no files yet
        DS.mark_design_done(d, by=designer)
    assert e.value.field == "files"
    design_file(d)
    bot_events.clear()
    DS.mark_design_done(d, by=designer)
    d.refresh_from_db()
    assert (d.stage, d.done, d.done_by, d.done_at, d.rev) == ("review", True, designer, NOW, 1)
    changed = bot_events.one("offer.changed")
    assert changed["how"] == "done" and changed["to"] == [9001]
    present = bot_events.one("offer.present")
    assert present["how"] == "ready" and present["to"] == [9003]
    assert present["task"]["stage"] == "review"
    note = flow.invoice.notes.get(kind=NoteKind.metering, meta__event="design_done")
    assert note.meta["design_id"] == d.pk and note.meta["round"] == 1
    with pytest.raises(ServiceConflict):
        DS.mark_design_done(d, by=designer)


def test_design_done_sms_to_a_manager_without_telegram(
    flow, designer, manager, commit, monkeypatch
):
    sent = []
    monkeypatch.setattr("metering.tasks.offer_sms.delay", lambda *a: sent.append(a))
    manager.telegram_id = None
    manager.save()
    design_file(flow.design)
    commit(DS.mark_design_done, flow.design, by=designer)
    assert sent == [("design", flow.design.pk, 1, "ready")]


def test_unassigned_design_can_be_done_by_a_design_user(operator, ali, pricer, manager, make_staff):
    from metering.design.models import Design

    m = finished(operator, ali, None, pricer, manager, step="price")
    d = M.start_design(m)
    assert d.user is None and d.due_at == datetime(2026, 11, 5, 18, 0)
    design_file(d)
    nobody = make_staff("design.change_design")
    with pytest.raises(ServiceForbidden):
        DS.mark_design_done(d, by=nobody)
    worker = make_staff("oauth.user_design")
    DS.mark_design_done(d, by=worker)
    assert Design.objects.get(pk=d.pk).stage == "review"


def test_price_done_is_not_blocked_by_the_design(flow, pricer):
    """The design is still in work: the price can be finished anyway."""
    assert flow.design.stage == "work"
    PS.mark_price_done(flow.price, by=pricer)
    assert Metering.objects.get(pk=flow.pk).price.stage == "review"


def test_price_done_price_only(operator, ali, pricer, manager, bot_events, make_staff):
    m = finished(operator, ali, None, pricer, manager, step="price")
    stranger = make_staff("price.change_price")
    with pytest.raises(ServiceForbidden):
        PS.mark_price_done(m.price, by=stranger)
    bot_events.clear()
    PS.mark_price_done(m.price, by=pricer)
    assert bot_events.one("offer.present")["task"]["kind"] == "price"
    assert bot_events.one("offer.changed")["how"] == "done"
    with pytest.raises(ServiceConflict):
        PS.mark_price_done(m.price, by=pricer)


# ------------------------------------------------------------------ move the deadline
def test_set_design_due(flow, designer, manager, bot_events, make_staff):
    d = flow.design
    bot_events.clear()
    DS.set_design_due(d, by=designer, preset="1d")
    d.refresh_from_db()
    assert d.due_at == datetime(2026, 11, 6, 18, 0) and d.rev == 1
    ev = bot_events.one("offer.changed")
    assert ev["how"] == "due_moved" and ev["to"] == [9001]
    assert ev["watchers"] == [9003]  # the manager is told
    DS.set_design_due(d, by=designer, text="07.11 09:00")
    assert d.due_at == datetime(2026, 11, 7, 9, 0)
    # past -> 400 field due; nothing changed
    with pytest.raises(ServiceError) as e:
        DS.set_design_due(d, by=designer, due_at=NOW - timedelta(hours=1))
    assert e.value.field == "due"
    # the manager moving it is not told about their own move
    boss = make_staff("metering.manage_metering")
    bot_events.clear()
    DS.set_design_due(d, by=boss, preset="1d")
    assert bot_events.one("offer.changed")["watchers"] == [9003]
    bot_events.clear()
    DS.set_design_due(d, by=make_staff("metering.manage_metering"), preset="1d")
    assert bot_events.one("offer.changed")["to"] == [9001]
    with pytest.raises(ServiceForbidden):
        DS.set_design_due(d, by=make_staff("design.view_design"), preset="1d")


def test_due_watchers_skip_the_manager_himself(flow, manager, bot_events):
    manager.user_permissions.add(Permission.objects.get(codename="manage_metering"))
    manager = type(manager).objects.get(pk=manager.pk)
    bot_events.clear()
    DS.set_design_due(flow.design, by=manager, preset="1d")
    ev = bot_events.one("offer.changed")
    assert ev["to"] == [9001] and ev["watchers"] == []


def test_set_due_needs_work_stage(flow, designer, pricer):
    ready_design(flow, designer)
    with pytest.raises(ServiceConflict):
        DS.set_design_due(flow.design, by=designer, preset="1d")
    PS.mark_price_done(flow.price, by=pricer)
    with pytest.raises(ServiceConflict):  # a price at the client has no deadline to move
        PS.set_price_due(flow.price, by=pricer, preset="1d")


def test_set_designer_and_pricer(flow, designer, make_staff, bot_events):
    other = make_staff("oauth.user_design", "design.view_design", telegram_id=9020)
    with pytest.raises(ServiceForbidden):
        DS.set_designer(flow.design, by=designer, user=other)
    boss = make_staff("metering.manage_metering")
    with pytest.raises(ServiceError):
        DS.set_designer(flow.design, by=boss, user=boss)  # cannot draw
    bot_events.clear()
    DS.set_designer(flow.design, by=boss, user=other)
    assert bot_events.one("offer.assigned")["to"] == [9020]
    assert bot_events.one("offer.changed")["to"] == [9001]
    pboss = make_staff("metering.manage_metering")
    newp = make_staff("price.change_price", "price.view_price")
    PS.set_pricer(flow.price, by=pboss, user=newp)
    assert Metering.objects.get(pk=flow.pk).price.user == newp


# ------------------------------------------------------------------ design answers
def test_design_approved_does_not_touch_the_running_price(
    flow, designer, manager, pricer, bot_events
):
    ready_design(flow, designer)
    bot_events.clear()
    out = DS.record_design_answer(flow.design, by=manager, answer="approved")
    assert out["closed_tasks"] == 0
    m = Metering.objects.get(pk=flow.pk)
    assert (m.design.stage, m.design.confirm, m.design.done) == ("approved", True, True)
    p = m.price  # the price has been running since «Bajarildi»: nothing changes
    assert (p.stage, p.due_at, p.assigned_at, p.rev) == (
        "work", datetime(2026, 11, 4, 18, 0), NOW, 0,
    )  # fmt: skip
    assert bot_events.of("offer.assigned") == []
    answered = bot_events.one("offer.changed")
    assert answered["how"] == "answered" and answered["answer"] == "approved"
    assert answered["to"] == [9003]
    assert m.offer_answers.get().answer == "approved"
    assert m.invoice.notes.filter(meta__event="design_approved").exists()
    with pytest.raises(ServiceConflict):
        DS.record_design_answer(flow.design, by=manager, answer="approved")


def test_design_answer_rules(flow, designer, manager, make_staff):
    d = flow.design
    with pytest.raises(ServiceError) as e:  # still being drawn
        DS.record_design_answer(d, by=manager, answer="approved")
    assert not isinstance(e.value, (ServiceConflict, ServiceForbidden))
    ready_design(flow, designer)
    other = make_staff("metering.present_to_client", telegram_id=9030)
    with pytest.raises(ServiceForbidden):  # the metering has its own manager
        DS.record_design_answer(d, by=other, answer="approved")
    with pytest.raises(ServiceError) as e:
        DS.record_design_answer(d, by=manager, answer="maybe")
    assert e.value.field == "answer"
    for answer in ("changes", "declined"):
        with pytest.raises(ServiceError) as e:
            DS.record_design_answer(d, by=manager, answer=answer, comment=" a ")
        assert e.value.field == "comment"
    with pytest.raises(ServiceError) as e:
        DS.record_design_answer(
            d, by=manager, answer="changes", comment="rangni o'zgartiring", due_at=NOW
        )
    assert e.value.field == "due"
    boss = make_staff("metering.manage_metering")
    DS.record_design_answer(d, by=boss, answer="approved")  # a zamer boss may answer


def test_unassigned_manager_row_accepts_any_presenter(operator, ali, pricer, make_staff):
    """Legacy: a metering without a manager is open to every present_to_client holder."""
    m = finished(operator, ali, None, pricer, make_staff("metering.present_to_client"), "price")
    Metering.objects.filter(pk=m.pk).update(manager=None)
    PS.mark_price_done(m.price, by=pricer)
    assert not M.can_present(make_staff("metering.view_metering"), Metering.objects.get(pk=m.pk))
    anyone = make_staff("metering.present_to_client")
    PS.record_price_answer(m.price, by=anyone, answer="approved")


def test_design_changes_goes_back_to_the_designer(flow, designer, manager, bot_events):
    ready_design(flow, designer)
    bot_events.clear()
    DS.record_design_answer(flow.design, by=manager, answer="changes", comment="Rang ochroq")
    d = Metering.objects.get(pk=flow.pk).design
    assert (d.stage, d.done, d.round, d.assigned_at) == ("work", False, 2, NOW)
    assert d.due_at == datetime(2026, 11, 4, 18, 0)  # DESIGN_FIX_DAYS = 1
    back = bot_events.one("offer.assigned")
    assert back["how"] == "changes" and back["comment"] == "Rang ochroq" and back["to"] == [9001]
    assert back["task"]["round"] == 2
    ans = bot_events.one("offer.changed")
    assert ans["how"] == "answered" and ans["answer"] == "changes"
    assert ans["task"]["rev"] > back["task"]["rev"]
    row = OfferAnswer.objects.get()
    assert (row.kind, row.round, row.comment) == ("design", 1, "Rang ochroq")
    assert d.metering.offer_answers.count() == 1
    # the price keeps running
    assert Metering.objects.get(pk=flow.pk).price.stage == "work"
    # the designer redoes it: round 2, new answer round 2
    design_file(d)
    DS.mark_design_done(d, by=designer)
    DS.record_design_answer(
        d, by=manager, answer="changes", comment="yana", due_at=datetime(2026, 11, 8, 12, 0)
    )
    assert Metering.objects.get(pk=flow.pk).design.due_at == datetime(2026, 11, 8, 12, 0)
    assert list(OfferAnswer.objects.values_list("round", flat=True)) == [1, 2]


def test_design_declined_closes_the_lead(flow, designer, manager, operator, bot_events):
    task = CC.create_task(
        flow.invoice, text="Qo'ng'iroq", due_at=NOW, by=operator, assigned_to=operator
    )
    ready_design(flow, designer)
    bot_events.clear()
    out = DS.record_design_answer(flow.design, by=manager, answer="declined", comment="Yoqmadi")
    assert out["closed_tasks"] == 1
    m = Metering.objects.get(pk=flow.pk)
    inv = m.invoice.__class__.objects.get(pk=m.invoice_id)
    assert inv.solution == SolutionChoice.declined
    assert m.client_result == ClientResult.design_declined
    assert m.status == MeteringStatus.done
    assert (m.design.stage, m.price.stage) == ("declined", "cancelled")
    assert InvoiceTask.objects.get(pk=task.pk).done_at is not None
    closed = bot_events.one("crm.task_closed")
    assert closed["how"] == "auto" and closed["to"] == [4001]
    cancelled = [e for e in bot_events.of("offer.changed") if e["how"] == "cancelled"]
    assert cancelled[0]["to"] == [9002] and cancelled[0]["task"]["kind"] == "price"
    line = inv.notes.get(meta__event="design_declined")
    assert line.text == "Yoqmadi" and line.meta["closed_tasks"] == 1
    assert not inv.notes.filter(meta__event="design_declined").count() > 1
    # a new zamer can be booked for the lead after the refusal
    new = M.create_metering(
        client=m.client, date_time=WHEN, invoice=inv, author=operator, measurer=flow.measurer
    )
    assert new.invoice_id == inv.pk
    assert Metering.objects.get(pk=m.pk).invoice_id is None


# ------------------------------------------------------------------ price answers
def approved_design(flow, designer, manager):
    ready_design(flow, designer)
    DS.record_design_answer(flow.design, by=manager, answer="approved")
    return Metering.objects.get(pk=flow.pk)


def test_price_approved_tells_the_order_makers(
    flow, designer, manager, pricer, make_staff, bot_events
):
    make_staff("order.add_order", telegram_id=9040)
    m = approved_design(flow, designer, manager)
    PS.mark_price_done(m.price, by=pricer)
    bot_events.clear()
    PS.record_price_answer(m.price, by=manager, answer="approved")
    m = Metering.objects.get(pk=flow.pk)
    assert m.client_result == ClientResult.agreed and m.price.stage == "approved"
    assert m.status == MeteringStatus.done  # the lead stays «go_for_measured»
    assert m.invoice.__class__.objects.get(pk=m.invoice_id).solution == (
        SolutionChoice.go_for_measured
    )
    ready = bot_events.one("offer.order_ready")
    assert ready["to"] == [9040]
    assert ready["url"].endswith(f"/orders/new?metering={m.pk}&design={m.design.pk}")
    # when the manager can make orders himself, only he is told
    manager.user_permissions.add(
        Permission.objects.get(codename="add_order", content_type__app_label="order")
    )
    m2 = finished(
        flow.invoice and make_staff("call_center.add_invoice"),
        flow.measurer,
        None,
        pricer,
        manager,
        "price",
    )
    PS.mark_price_done(m2.price, by=pricer)
    bot_events.clear()
    PS.record_price_answer(m2.price, by=manager, answer="approved")
    assert bot_events.one("offer.order_ready")["to"] == [9003]


def test_price_recalc_and_declined(flow, designer, manager, pricer, operator, bot_events):
    m = approved_design(flow, designer, manager)
    PS.mark_price_done(m.price, by=pricer)
    bot_events.clear()
    PS.record_price_answer(m.price, by=manager, answer="recalc", comment="Arzonroq")
    p = Metering.objects.get(pk=flow.pk).price
    assert (p.stage, p.done, p.round) == ("work", False, 2)
    assert p.due_at == datetime(2026, 11, 4, 18, 0)  # PRICE_FIX_DAYS = 1
    assert bot_events.one("offer.assigned")["how"] == "changes"
    PS.mark_price_done(p, by=pricer)
    out = PS.record_price_answer(p, by=manager, answer="declined", comment="Qimmat")
    m = Metering.objects.get(pk=flow.pk)
    assert out["closed_tasks"] == 0
    assert m.client_result == ClientResult.price_declined and m.price.stage == "declined"
    assert m.design.stage == "approved"
    inv = m.invoice.__class__.objects.get(pk=m.invoice_id)
    assert inv.solution == SolutionChoice.price_problem
    assert inv.notes.filter(meta__event="price_declined", text="Qimmat").exists()
    with pytest.raises(ServiceConflict):
        PS.record_price_answer(p, by=manager, answer="approved")


# ------------------------------------------------------------------ close_lead_from_offer
def test_close_lead_from_offer_rules(flow, operator, manager):
    inv = flow.invoice
    kw = dict(by=manager, solution=SolutionChoice.declined, reason="x", metering_id=flow.pk)
    CC.close_lead_from_offer(inv, event="design_declined", **kw)
    # already closed: only logged
    CC.close_lead_from_offer(inv, event="design_declined", **kw)
    assert inv.notes.filter(meta__event="design_declined").count() == 2
    assert inv.__class__.objects.get(pk=inv.pk).solution == SolutionChoice.declined
    inv.__class__.objects.filter(pk=inv.pk).update(solution=SolutionChoice.sold_out)
    with pytest.raises(ServiceConflict):
        CC.close_lead_from_offer(inv, event="design_declined", **kw)


def test_declined_answer_after_the_order_is_a_conflict(flow, designer, manager):
    ready_design(flow, designer)
    flow.invoice.__class__.objects.filter(pk=flow.invoice_id).update(
        solution=SolutionChoice.sold_out
    )
    with pytest.raises(ServiceConflict):
        DS.record_design_answer(flow.design, by=manager, answer="declined", comment="yo'q")
    d = Metering.objects.get(pk=flow.pk).design
    assert d.stage == "review" and not OfferAnswer.objects.exists()  # rolled back


# ------------------------------------------------------------------ order
def test_order_from_a_price_only_metering(
    operator, ali, pricer, manager, admin_api, default_factory
):
    m = finished(operator, ali, None, pricer, manager, step="price")
    r = admin_api.post(
        "/api/v1/orders/",
        {"metering": m.pk, "address": "Chilonzor", "count_days": 30},
        format="json",
    )
    assert r.status_code == 201, r.content
    # a design_price metering still needs its design
    m2 = finished(operator, ali, None, pricer, manager, step="price")
    Metering.objects.filter(pk=m2.pk).update(next_step="design_price")
    r = admin_api.post(
        "/api/v1/orders/", {"metering": m2.pk, "address": "x", "count_days": 30}, format="json"
    )
    assert r.status_code == 400


# ------------------------------------------------------------------ reminders
def reminders(clock, when):
    clock["v"] = when
    return M.due_offer_reminders(when)


def test_reminder_soon_assigned_early(flow, designer, bot_events, clock):
    quiet_price(flow)
    # due Thu 05.11 18:00, assigned Tue 12:00 (54 h before): remind Wed 04.11 09:00
    assert reminders(clock, datetime(2026, 11, 4, 8, 59))["soon"] == 0
    bot_events.clear()
    assert reminders(clock, datetime(2026, 11, 4, 9, 0))["soon"] == 1
    ev = bot_events.one("offer.reminder")
    assert ev["kind"] == "soon" and ev["to"] == [9001] and ev["task"]["kind"] == "design"
    assert reminders(clock, datetime(2026, 11, 4, 9, 5))["soon"] == 0  # once per revision
    assert reminders(clock, datetime(2026, 11, 5, 17, 59))["soon"] == 0


def test_reminder_soon_assigned_late_uses_the_deadline_day(flow, designer, clock):
    quiet_price(flow)
    from metering.design.models import Design

    # assigned 35 h before: 09:00 on the deadline day
    Design.objects.filter(pk=flow.design.pk).update(
        assigned_at=datetime(2026, 11, 4, 7, 0), due_at=datetime(2026, 11, 5, 18, 0)
    )
    assert reminders(clock, datetime(2026, 11, 4, 12, 0))["soon"] == 0
    assert reminders(clock, datetime(2026, 11, 5, 9, 0))["soon"] == 1
    # a deadline before 09:00: two hours before it
    Design.objects.filter(pk=flow.design.pk).update(
        due_at=datetime(2026, 11, 6, 8, 0), assigned_at=datetime(2026, 11, 6, 1, 0), rev=5
    )
    assert reminders(clock, datetime(2026, 11, 6, 5, 59))["soon"] == 0
    assert reminders(clock, datetime(2026, 11, 6, 6, 0))["soon"] == 1


def test_reminder_not_for_a_task_assigned_after_the_reminder_moment(flow, clock):
    from metering.design.models import Design

    Design.objects.filter(pk=flow.design.pk).update(
        assigned_at=datetime(2026, 11, 5, 10, 0), due_at=datetime(2026, 11, 5, 18, 0)
    )
    assert reminders(clock, datetime(2026, 11, 5, 11, 0))["soon"] == 0


def test_reminder_late_and_overdue(flow, designer, bot_events, clock):
    quiet_price(flow)
    bot_events.clear()
    assert reminders(clock, datetime(2026, 11, 5, 18, 0))["late"] == 1
    assert bot_events.one("offer.reminder")["kind"] == "late"
    assert reminders(clock, datetime(2026, 11, 5, 18, 30))["late"] == 0
    assert reminders(clock, datetime(2026, 11, 5, 23, 0))["overdue"] == 0  # not yet a morning
    bot_events.clear()
    assert reminders(clock, datetime(2026, 11, 6, 9, 0))["overdue"] == 1
    assert bot_events.one("offer.reminder")["kind"] == "overdue"
    assert reminders(clock, datetime(2026, 11, 6, 9, 30))["overdue"] == 0  # once a day
    assert reminders(clock, datetime(2026, 11, 7, 9, 0))["overdue"] == 1
    assert reminders(clock, datetime(2026, 11, 13, 9, 0))["overdue"] == 0  # a week is enough


def test_reminder_rearms_on_a_new_revision(flow, designer, clock):
    quiet_price(flow)
    assert reminders(clock, datetime(2026, 11, 5, 18, 0))["late"] == 1
    DS.set_design_due(flow.design, by=designer, due_at=datetime(2026, 11, 5, 20, 0))
    assert reminders(clock, datetime(2026, 11, 5, 20, 0))["late"] == 1


def test_reminders_skip_unreachable_and_finished(
    flow, designer, clock, operator, ali, pricer, manager
):
    quiet_price(flow)
    designer.telegram_id = None
    designer.save()
    assert reminders(clock, datetime(2026, 11, 5, 18, 0))["late"] == 0
    designer.telegram_id = 9001
    designer.is_active = False
    designer.save()
    assert reminders(clock, datetime(2026, 11, 5, 18, 0))["late"] == 0
    designer.is_active = True
    designer.save()
    ready_design(flow, designer)  # in review: not a designer reminder any more
    assert reminders(clock, datetime(2026, 11, 5, 18, 0))["late"] == 0


def test_manager_is_nudged_then_daily(flow, designer, manager, bot_events, clock):
    ready_design(flow, designer)  # done_at = NOW
    bot_events.clear()
    assert reminders(clock, datetime(2026, 11, 4, 11, 59))["present"] == 0
    assert reminders(clock, datetime(2026, 11, 4, 12, 0))["present"] == 1
    ev = bot_events.one("offer.present")
    assert ev["how"] == "reminder" and ev["to"] == [9003]
    assert reminders(clock, datetime(2026, 11, 4, 12, 30))["present"] == 0
    assert reminders(clock, datetime(2026, 11, 5, 8, 59))["present"] == 0
    assert reminders(clock, datetime(2026, 11, 5, 9, 0))["present"] == 1
    assert reminders(clock, datetime(2026, 11, 5, 9, 30))["present"] == 0
    assert reminders(clock, datetime(2026, 11, 20, 9, 0))["present"] == 0  # given up
    # answered: no more nudges
    DS.record_design_answer(flow.design, by=manager, answer="approved")
    assert reminders(clock, datetime(2026, 11, 6, 9, 0))["present"] == 0


def test_legacy_row_without_a_manager_goes_to_the_only_manager(flow, designer, manager, bot_events):
    Metering.objects.filter(pk=flow.pk).update(manager=None)
    design_file(flow.design)
    bot_events.clear()
    DS.mark_design_done(flow.design, by=designer)
    assert bot_events.one("offer.present")["to"] == [9003]


def test_legacy_row_with_two_managers_goes_to_nobody(flow, designer, make_staff, bot_events):
    Metering.objects.filter(pk=flow.pk).update(manager=None)
    make_staff("metering.present_to_client", telegram_id=9050)
    design_file(flow.design)
    bot_events.clear()
    DS.mark_design_done(flow.design, by=designer)
    assert bot_events.of("offer.present") == []


def test_schedule_has_the_offer_reminder_job():
    from accounting.schedule import periodic_tasks

    assert periodic_tasks()["dizayn/narx: eslatmalar"] == (
        "metering.tasks.offer_reminders",
        {"minute": "*"},
    )


def test_offer_sms_task(flow, manager, monkeypatch):
    from metering import tasks

    sms = []
    monkeypatch.setattr("core.sms.send_bulk_sms", lambda msgs: sms.extend(msgs))
    d = flow.design
    assert tasks.offer_sms("design", d.pk, d.rev, "assigned") is False  # has Telegram
    manager.telegram_id = None
    manager.save()
    assert tasks.offer_sms("design", d.pk, d.rev + 5, "ready") is False  # revision changed
    assert tasks.offer_sms("design", d.pk, d.rev, "ready") is True
    assert tasks.offer_sms("design", d.pk, d.rev, "ready") is False  # once
    assert len(sms) == 1 and "dizayni tayyor" in sms[0]["text"]


# ------------------------------------------------------------------ agenda / presentations
def test_offer_agenda_buckets(flow, designer, clock, make_staff):
    from metering.design.models import Design

    qs = Design.objects.all()
    Design.objects.filter(pk=flow.design.pk).update(due_at=datetime(2026, 11, 3, 9, 0))
    out = M.offer_agenda(qs, now=NOW)
    assert out["counts"] == {
        "overdue": 1, "today": 0, "work": 1, "review": 0, "archive": 0,
    }  # fmt: skip
    Design.objects.filter(pk=flow.design.pk).update(due_at=datetime(2026, 11, 3, 18, 0))
    out = M.offer_agenda(qs, now=NOW)
    assert out["counts"]["today"] == 1 and out["counts"]["overdue"] == 0
    ready_design(flow, designer)
    out = M.offer_agenda(qs, now=NOW)
    assert out["counts"]["review"] == 1 and out["counts"]["work"] == 0
    from metering.price.models import Price

    # the price runs next to the design: it has its own deadline and is in work
    assert M.offer_agenda(Price.objects.all(), now=NOW)["counts"]["work"] == 1


def test_offer_queryset_scoping(flow, designer, make_staff):
    from metering.design.models import Design

    qs = Design.objects.all()
    assert list(M.offer_queryset_for(designer, qs, kind="design")) == [flow.design]
    other = make_staff("design.view_design")
    assert list(M.offer_queryset_for(other, qs, kind="design")) == []
    boss = make_staff("metering.manage_metering")
    assert M.offer_queryset_for(boss, qs, kind="design").count() == 1


def test_presentations_buckets(flow, designer, manager, pricer, make_staff):
    p = M.presentations(manager, now=NOW)
    assert [r["metering"].pk for r in p["working"]] == [flow.pk]
    assert p["working"][0]["waiting_for"] == "design" and p["review"] == []
    ready_design(flow, designer)
    p = M.presentations(manager, now=NOW)
    assert [r["metering"].pk for r in p["review"]] == [flow.pk] and p["working"] == []
    assert p["review"][0]["is_overdue"] is False
    later = NOW + timedelta(hours=25)
    assert M.presentations(manager, now=later)["review"][0]["is_overdue"] is True
    DS.record_design_answer(flow.design, by=manager, answer="approved")
    p = M.presentations(manager, now=NOW)
    assert p["working"][0]["waiting_for"] == "price"
    PS.mark_price_done(Metering.objects.get(pk=flow.pk).price, by=pricer)
    PS.record_price_answer(Metering.objects.get(pk=flow.pk).price, by=manager, answer="approved")
    p = M.presentations(manager, now=NOW)
    assert [r["metering"].pk for r in p["order_ready"]] == [flow.pk]
    # another manager sees nothing of this one; a zamer boss sees all
    other = make_staff("metering.present_to_client")
    assert M.presentations(other, now=NOW)["order_ready"] == []
    boss = make_staff("metering.manage_metering")
    assert len(M.presentations(boss, now=NOW)["order_ready"]) == 1


# ------------------------------------------------------------------ access flags
def test_access_flags_exist():
    from oauth.access import SECTIONS, _view

    by_key = {s.key: s for s in SECTIONS}
    assert _view(by_key["design_designer"]) == {"oauth.user_design"}
    assert "design_manager" not in by_key and "price_manager" not in by_key
    assert _view(by_key["metering_manager"]) == {"metering.manage_metering"}
    assert _view(by_key["metering_presenter"]) == {"metering.present_to_client"}
    assert not any(by_key[k].edit for k in by_key if k in (
        "design_designer", "metering_manager", "metering_presenter"
    ))  # fmt: skip


# ------------------------------------------------------------------ site API
def as_user(user):
    from rest_framework.test import APIClient

    c = APIClient()
    c.force_authenticate(user)
    return c


def test_api_finish_with_manager_and_deadlines(api, operator, ali, designer, pricer, manager):
    inv = lead(operator)
    m = M.create_metering(
        client=inv.client, date_time=WHEN, invoice=inv, author=operator, measurer=ali
    )
    M.mark_metering_measured(m, by=ali)
    upload_file(m)
    c = as_user(ali)
    url = f"/api/v1/meterings/{m.pk}/finish/"
    body = {"note": "ok", "next_step": "design_price", "designer": designer.pk, "pricer": pricer.pk}
    r = c.post(url, {**body, "price_due_at": "2026-11-01T10:00:00"}, format="json")
    assert r.status_code == 400 and r.data["field"] == "price_due"
    r = c.post(url, {**body, "design_due_at": "2026-11-01T10:00:00"}, format="json")
    assert r.status_code == 400 and r.data["field"] == "design_due"
    r = c.post(
        url,
        {
            **body,
            "manager": manager.pk,
            "design_due_at": "2026-11-09T12:00:00",
            "price_due_at": "2026-11-06T15:00:00",
        },
        format="json",
    )
    assert r.status_code == 200, r.content
    assert r.data["manager"]["id"] == manager.pk and r.data["client_result"] == ""
    assert r.data["design"]["stage"] == "work" and r.data["design"]["due_at"].startswith(
        "2026-11-09T12:00"
    )
    assert r.data["price"]["stage"] == "work" and r.data["price"]["user"]["id"] == pricer.pk
    assert r.data["price"]["due_at"].startswith("2026-11-06T15:00")
    assert r.data["design"]["is_overdue"] is False and r.data["design"]["last_comment"] is None


def test_api_assignees_extension(api, flow, designer, manager, make_staff):
    c = as_user(make_staff("metering.manage_metering"))
    r = c.get("/api/v1/meterings/assignees/")
    assert r.status_code == 200
    assert [u["id"] for u in r.data["managers"]] == [manager.pk]
    assert r.data["default_manager"] == manager.pk and "hint" not in r.data
    assert set(r.data["defaults"]) == {"design_due_at", "price_due_at"}
    assert r.data["defaults"]["design_due_at"].startswith("2026-11-05T18:00")
    assert as_user(manager).get("/api/v1/meterings/assignees/").status_code == 200
    assert (
        as_user(make_staff("metering.view_metering"))
        .get("/api/v1/meterings/assignees/")
        .status_code
        == 403
    )
    type(manager).objects.filter(pk=manager.pk).update(is_active=False)
    r = c.get("/api/v1/meterings/assignees/")
    assert r.data["managers"] == [] and r.data["default_manager"] is None and r.data["hint"]


def test_api_design_agenda_and_scoping(flow, designer, manager, make_staff, operator, ali, pricer):
    other = finished(operator, ali, designer, pricer, manager)
    from metering.design.models import Design

    Design.objects.filter(pk=other.design.pk).update(user=make_staff("oauth.user_design"))
    c = as_user(designer)
    r = c.get("/api/v1/designs/agenda/")
    assert r.status_code == 200, r.content
    assert set(r.data) == {"counts", "overdue", "today", "work", "review"}
    assert set(r.data["counts"]) == {"overdue", "today", "work", "review", "archive"}
    assert [d["id"] for d in r.data["work"]] == [flow.design.pk]  # only mine
    boss = as_user(make_staff("design.view_design", "metering.manage_metering"))
    r = boss.get("/api/v1/designs/agenda/")
    assert r.data["counts"]["work"] == 2
    r = boss.get(f"/api/v1/designs/agenda/?user={designer.pk}")
    assert [d["id"] for d in r.data["work"]] == [flow.design.pk]
    r = boss.get("/api/v1/designs/agenda/?user=me")
    assert r.status_code == 200, r.content
    assert r.data["counts"]["work"] == 0
    assert boss.get("/api/v1/designs/agenda/?search=zzz").data["counts"]["work"] == 0
    assert boss.get("/api/v1/designs/agenda/?search=Karim").data["counts"]["work"] == 2
    row = boss.get("/api/v1/designs/agenda/").data["work"][0]
    assert row["stage"] == "work" and row["stage_label"] == "Ishda" and row["round"] == 1
    assert row["manager"]["id"] == manager.pk and row["measurer"]["id"] == ali.pk
    assert row["result_note"] == "Hammasi o'lchandi" and row["is_overdue"] is False
    # list and ?stage= filter
    r = boss.get("/api/v1/designs/?stage=review,approved")
    assert r.data["count"] == 0
    assert boss.get("/api/v1/designs/?stage=work").data["count"] == 2


def test_api_design_flow(flow, designer, manager, bot_events, make_staff):
    c, mc = as_user(designer), as_user(manager)
    url = f"/api/v1/designs/{flow.design.pk}"
    r = c.get(f"{url}/")
    assert r.status_code == 200
    assert r.data["file_count"] == 0 and r.data["answers"] == []
    assert (
        r.data["actions"]["done"] and r.data["actions"]["due"] and not r.data["actions"]["answer"]
    )
    assert not r.data["actions"]["reassign"]
    r = c.post(f"{url}/done/")
    assert r.status_code == 400 and r.data["field"] == "files"
    design_file(flow.design)
    assert c.get(f"{url}/").data["file_count"] == 1
    r = c.post(f"{url}/due/", {"due_at": "2026-11-01T10:00:00"}, format="json")
    assert r.status_code == 400 and r.data["field"] == "due"
    r = c.post(f"{url}/due/", {"due_at": "2026-11-09T12:00:00"}, format="json")
    assert r.status_code == 200 and r.data["due_at"].startswith("2026-11-09T12:00")
    r = c.post(f"{url}/done/")
    assert r.status_code == 200 and r.data["stage"] == "review" and r.data["done"] is True
    assert r.data["actions"]["done"] is False and r.data["actions"]["due"] is False
    # only the manager answers
    assert c.get(f"{url}/").data["actions"]["answer"] is False
    assert mc.get(f"{url}/").data["actions"]["answer"] is True
    r = c.post(f"{url}/answer/", {"answer": "approved"}, format="json")
    assert r.status_code == 400  # ServiceForbidden is a 400 on the site
    r = mc.post(f"{url}/answer/", {"answer": "changes"}, format="json")
    assert r.status_code == 400 and r.data["field"] == "comment"
    r = mc.post(f"{url}/answer/", {"answer": "changes", "comment": "Rang"}, format="json")
    assert r.status_code == 200 and r.data["stage"] == "work" and r.data["round"] == 2
    assert r.data["answers"][0]["answer_label"] == "O'zgartirish kerak"
    assert r.data["answers"][0]["by"]["id"] == manager.pk and r.data["last_comment"] == "Rang"
    assert r.data["closed_tasks"] == 0
    boss = as_user(make_staff("design.view_design", "metering.manage_metering"))
    other = make_staff("oauth.user_design", "design.view_design")
    r = boss.post(f"{url}/designer/", {"user": other.pk}, format="json")
    assert r.status_code == 200 and r.data["user_detail"]["id"] == other.pk
    assert boss.post(f"{url}/designer/", {"user": 99999}, format="json").status_code == 404


def test_api_price_flow(flow, designer, manager, pricer, make_staff):
    c, mc = as_user(pricer), as_user(manager)
    mc_design = f"/api/v1/designs/{flow.design.pk}"
    url = f"/api/v1/prices/{flow.price.pk}"
    r = c.get(f"{url}/")
    assert r.data["stage"] == "work" and r.data["due_at"].startswith("2026-11-04T18:00")
    assert r.data["actions"]["done"] is True  # not blocked by the design
    agenda = c.get("/api/v1/prices/agenda/").data
    assert agenda["counts"]["work"] == 1 and agenda["work"][0]["id"] == flow.price.pk
    assert "waiting" not in agenda
    ready_design(flow, designer)
    assert mc.post(f"{mc_design}/answer/", {"answer": "approved"}, format="json").status_code == 200
    assert c.get(f"{url}/").data["stage"] == "work"  # the design's approval changes nothing
    r = c.post(f"{url}/due/", {"due_at": "2026-11-10T10:00:00"}, format="json")
    assert r.status_code == 200 and r.data["due_at"].startswith("2026-11-10T10:00")
    assert c.post(f"{url}/done/").status_code == 200
    r = mc.post(f"{url}/answer/", {"answer": "approved"}, format="json")
    assert r.status_code == 200 and r.data["stage"] == "approved"
    assert r.data["client_result"] == "agreed" and r.data["answers"][0]["answer_label"] == "Rozi"
    boss = as_user(make_staff("price.view_price", "metering.manage_metering"))
    r = boss.post(
        f"{url}/pricer/",
        {"user": make_staff("price.change_price", "price.view_price").pk},
        format="json",
    )
    assert r.status_code == 400  # approved: closed


def test_api_presentations(flow, designer, manager, make_staff):
    c = as_user(manager)
    r = c.get("/api/v1/meterings/presentations/")
    assert r.status_code == 200, r.content
    assert set(r.data) == {"counts", "review", "working", "order_ready"}
    assert r.data["counts"] == {"review": 0, "overdue": 0, "working": 1, "order_ready": 0}
    row = r.data["working"][0]
    assert set(row) == {"metering", "design", "price", "manager", "waiting_for", "is_overdue"}
    assert row["waiting_for"] == "design" and row["manager"]["id"] == manager.pk
    assert row["design"]["stage"] == "work" and row["design"]["types"][0]["name"] == "Дизайн-1"
    assert row["price"]["stage"] == "work" and row["price"]["price"] is None
    assert row["metering"]["id"] == flow.pk
    ready_design(flow, designer)
    r = c.get("/api/v1/meterings/presentations/?manager=me")
    assert [x["metering"]["id"] for x in r.data["review"]] == [flow.pk]
    assert r.data["review"][0]["waiting_for"] is None
    assert (
        c.get(f"/api/v1/meterings/presentations/?manager={manager.pk + 99}").data["counts"][
            "review"
        ]
        == 0
    )
    assert c.get("/api/v1/meterings/presentations/?search=Karim").data["counts"]["review"] == 1
    assert c.get("/api/v1/meterings/presentations/?search=nobody").data["counts"]["review"] == 0
    # permissions
    assert as_user(designer).get("/api/v1/meterings/presentations/").status_code == 403
    assert (
        as_user(make_staff("metering.manage_metering"))
        .get("/api/v1/meterings/presentations/")
        .status_code
        == 200
    )
    assert (
        as_user(make_staff(superuser=True)).get("/api/v1/meterings/presentations/").status_code
        == 200
    )


def test_api_invoice_exposes_design_and_price_with_stable_queries(
    operator, ali, designer, pricer, manager, make_staff, django_assert_max_num_queries
):
    for i in range(4):
        inv = lead(operator, phone=f"+99890222{i:04d}")
        m = M.create_metering(
            client=inv.client, date_time=WHEN, invoice=inv, author=operator, measurer=ali
        )
        M.mark_metering_measured(m, by=ali)
        upload_file(m)
        M.finish_metering(
            m, by=ali, note="n", next_step="design_price", designer=designer, pricer=pricer
        )
    c = as_user(
        make_staff("call_center.view_invoice", "metering.view_metering", "client.view_client")
    )
    r = c.get("/api/v1/invoices/")
    assert r.status_code == 200
    got = [row["metering"] for row in r.data["results"]]
    assert all(g["manager"]["id"] == manager.pk and g["client_result"] == "" for g in got)
    d, p = got[0]["design"], got[0]["price"]
    assert set(d) == {
        "id", "stage", "stage_label", "due_at", "done_at", "is_overdue", "user", "round",
        "last_comment",
    }  # fmt: skip
    assert d["stage"] == "work" and p["stage"] == "work" and p["user"]["id"] == pricer.pk
    with django_assert_max_num_queries(16):
        c.get("/api/v1/invoices/")
    first = c.get("/api/v1/invoices/").data["results"][0]["id"]
    assert c.get(f"/api/v1/invoices/{first}/").status_code == 200


def test_api_metering_serializer_shows_the_offer_briefs(flow, designer, make_staff):
    c = as_user(make_staff("metering.view_metering"))
    r = c.get(f"/api/v1/meterings/{flow.pk}/")
    assert r.status_code == 200
    assert r.data["design"]["stage"] == "work" and r.data["design"]["done"] is False
    assert r.data["price"]["stage"] == "work"
    assert r.data["manager"]["id"] == flow.manager_id


def test_api_design_and_price_lists_have_stable_queries(
    operator, ali, designer, pricer, manager, make_staff, django_assert_max_num_queries
):
    def count(n):
        for i in range(n):
            finished(operator, ali, designer, pricer, manager)
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        c = as_user(make_staff(superuser=True))
        with CaptureQueriesContext(connection) as q:
            assert c.get("/api/v1/designs/").status_code == 200
            assert c.get("/api/v1/prices/").status_code == 200
            assert c.get("/api/v1/designs/agenda/").status_code == 200
        return len(q)

    one = count(1)
    assert count(3) <= one + 1  # the extra rows add no queries


# ------------------------------------------------------------------ fix round
def test_finish_without_any_manager_is_allowed_with_a_warning(
    operator, ali, designer, pricer, caplog, commit
):
    from metering.checks import no_manager_check

    assert [w.id for w in no_manager_check(None)] == ["metering.W002"]
    m = book_measured(operator, ali)
    with caplog.at_level("WARNING", logger="metering"):
        commit(
            M.finish_metering,
            m,
            by=ali,
            note="n",
            next_step="design_price",
            designer=designer,
            pricer=pricer,
        )
    got = Metering.objects.get(pk=m.pk)
    assert got.status == MeteringStatus.done and got.manager is None
    assert "without a manager" in caplog.text


def test_no_manager_check_is_quiet_with_a_manager(manager):
    from metering.checks import no_manager_check

    assert no_manager_check(None) == []


def test_patching_a_price_cannot_move_the_stage(flow, admin_api):
    p = flow.price
    r = admin_api.patch(
        f"/api/v1/prices/{p.pk}/",
        {
            "stage": "approved",
            "rev": 0,
            "round": 9,
            "done": True,
            "duration_days": 20,
            "due_at": "2030-01-01T10:00:00",
            "assigned_at": "2030-01-01T10:00:00",
            "done_at": "2030-01-01T10:00:00",
            "desc": "yangi izoh",
        },
        format="json",
    )
    assert r.status_code == 200, r.content
    from metering.price.models import Price

    now = Price.objects.get(pk=p.pk)
    assert now.desc == "yangi izoh"
    assert (now.stage, now.rev, now.round, now.done) == (p.stage, p.rev, p.round, False)
    assert (now.due_at, now.assigned_at, now.done_at) == (p.due_at, p.assigned_at, None)
    assert now.duration_days == p.duration_days


def test_recompute_price_total_leaves_the_stage_alone(flow):
    from metering.price.models import Price

    stale = Price.objects.get(pk=flow.price.pk)
    Price.objects.filter(pk=stale.pk).update(stage="work", rev=7)
    PS.recompute_price_total(stale)
    now = Price.objects.get(pk=stale.pk)
    assert (now.stage, now.rev) == ("work", 7)


def test_declining_keeps_done_equal_to_review_or_approved(flow, designer, manager, pricer):
    ready_design(flow, designer)
    assert Metering.objects.get(pk=flow.pk).design.done is True
    DS.record_design_answer(flow.design, by=manager, answer="declined", comment="Yoqmadi")
    d = Metering.objects.get(pk=flow.pk).design
    assert (d.stage, d.done) == ("declined", False)


def test_declined_price_is_not_done(flow, designer, manager, pricer):
    ready_design(flow, designer)
    DS.record_design_answer(flow.design, by=manager, answer="approved")
    m = Metering.objects.get(pk=flow.pk)
    PS.mark_price_done(m.price, by=pricer)
    PS.record_price_answer(m.price, by=manager, answer="declined", comment="Qimmat")
    p = Metering.objects.get(pk=flow.pk).price
    assert (p.stage, p.done) == ("declined", False)


def test_no_order_from_an_unapproved_or_refused_design(
    flow, designer, manager, admin_api, default_factory
):
    from metering.design.models import DesignType
    from order.models import Order

    body = {"metering": flow.pk, "address": "Chilonzor", "count_days": 30}
    vt = DesignType.objects.filter(design=flow.design).first()
    body["design_type"] = vt.pk
    # in work
    assert admin_api.post("/api/v1/orders/", body, format="json").status_code == 400
    # waiting for the client's answer
    ready_design(flow, designer)
    r = admin_api.post("/api/v1/orders/", body, format="json")
    assert r.status_code == 400 and not Order.objects.exists()
    # the action flag agrees
    assert (
        admin_api.get(f"/api/v1/designs/{flow.design.pk}/").data["actions"]["create_order"] is False
    )
    DS.record_design_answer(flow.design, by=manager, answer="approved")
    assert (
        admin_api.get(f"/api/v1/designs/{flow.design.pk}/").data["actions"]["create_order"] is True
    )
    # the client later refuses the price
    Metering.objects.filter(pk=flow.pk).update(client_result=ClientResult.price_declined)
    assert (
        admin_api.get(f"/api/v1/designs/{flow.design.pk}/").data["actions"]["create_order"] is False
    )
    r = admin_api.post("/api/v1/orders/", body, format="json")
    assert r.status_code == 400 and not Order.objects.exists()
    Metering.objects.filter(pk=flow.pk).update(client_result="")
    r = admin_api.post("/api/v1/orders/", body, format="json")
    assert r.status_code == 201, r.content


def test_no_order_from_a_declined_design(flow, designer, manager, admin_api, default_factory):
    from metering.design.models import DesignType

    vt = DesignType.objects.filter(design=flow.design).first()
    ready_design(flow, designer)
    DS.record_design_answer(flow.design, by=manager, answer="declined", comment="Yoqmadi")
    r = admin_api.post(
        "/api/v1/orders/",
        {"metering": flow.pk, "address": "x", "count_days": 30, "design_type": vt.pk},
        format="json",
    )
    assert r.status_code == 400


def test_changes_sms_is_queued_for_the_final_revision(flow, designer, manager, commit, monkeypatch):
    sent = []
    monkeypatch.setattr("metering.tasks.offer_sms.delay", lambda *a: sent.append(a))
    designer.telegram_id = None
    designer.save()
    ready_design(flow, designer)
    commit(
        DS.record_design_answer,
        flow.design,
        by=manager,
        answer="changes",
        comment="Rangini o'zgartiring",
    )
    d = Metering.objects.get(pk=flow.pk).design
    assert sent == [("design", d.pk, d.rev, "assigned")]


def test_recalc_sms_is_queued_for_the_final_revision(
    flow, designer, manager, pricer, commit, monkeypatch
):
    sent = []
    monkeypatch.setattr("metering.tasks.offer_sms.delay", lambda *a: sent.append(a))
    pricer.telegram_id = None
    pricer.save()
    ready_design(flow, designer)
    DS.record_design_answer(flow.design, by=manager, answer="approved")
    p = Metering.objects.get(pk=flow.pk).price
    PS.mark_price_done(p, by=pricer)
    sent.clear()
    commit(PS.record_price_answer, p, by=manager, answer="recalc", comment="Arzonroq qiling")
    p = Metering.objects.get(pk=flow.pk).price
    assert sent == [("price", p.pk, p.rev, "assigned")]


def test_presentations_query_count_does_not_grow(
    operator, ali, designer, pricer, manager, admin_api
):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    def count():
        with CaptureQueriesContext(connection) as ctx:
            r = admin_api.get("/api/v1/meterings/presentations/")
        assert r.status_code == 200
        return len(ctx), r.data

    def review(phone):
        inv = lead(operator, phone)
        m = M.create_metering(
            client=inv.client, date_time=WHEN, invoice=inv, author=operator, measurer=ali
        )
        M.mark_metering_measured(m, by=ali)
        upload_file(m)
        M.finish_metering(
            m, by=ali, note="n", next_step="design_price", designer=designer, pricer=pricer,
            manager=manager,
        )  # fmt: skip
        m = Metering.objects.get(pk=m.pk)
        design_file(m.design)
        DS.mark_design_done(m.design, by=designer)
        DS.record_design_answer(m.design, by=manager, answer="changes", comment="Qayta chizing")
        DS.mark_design_done(Metering.objects.get(pk=m.pk).design, by=designer)

    review("+998901110001")
    count()  # warm the process-wide caches (constance, permissions)
    one, data = count()
    assert len(data["review"]) == 1
    for i in range(2, 6):
        review(f"+99890111000{i}")
    many, data = count()
    assert len(data["review"]) == 5 and data["counts"]["review"] == 5
    assert many == one


def test_presentations_filters_before_the_cap(flow, designer, manager, make_staff):
    other = make_staff("metering.present_to_client", "metering.view_metering")
    boss = make_staff("metering.manage_metering")
    ready_design(flow, designer)
    out = M.presentations(boss, now=NOW, manager=other.pk)
    assert out["review"] == [] and out["counts"]["review"] == 0
    out = M.presentations(boss, now=NOW, manager=manager.pk, search="karim")
    assert [r["metering"].pk for r in out["review"]] == [flow.pk]
    assert out["counts"] == {"review": 1, "overdue": 0, "working": 0, "order_ready": 0}
    later = NOW + timedelta(hours=30)
    assert M.presentations(boss, now=later)["counts"]["overdue"] == 1


def test_assign_refuses_after_the_client_refused(flow, designer, manager, pricer, make_staff):
    ready_design(flow, designer)
    DS.record_design_answer(flow.design, by=manager, answer="declined", comment="Yoqmadi")
    other = make_staff("price.change_price", "price.view_price", name="Yangi")
    with pytest.raises(ServiceError):
        M.assign_metering_tasks(Metering.objects.get(pk=flow.pk), pricer=other)
    with pytest.raises(ServiceError):
        M.start_price(Metering.objects.get(pk=flow.pk))


def test_no_price_for_a_cancelled_design(operator, ali, designer, pricer, manager):
    from metering.design.models import Design

    m = finished(operator, ali, designer, pricer, manager, step="design_price")
    Design.objects.filter(metering=m).update(stage="cancelled")
    m.price.delete()
    with pytest.raises(ServiceError):
        M.assign_metering_tasks(Metering.objects.get(pk=m.pk), pricer=pricer)


def test_reminders_read_the_default_manager_once(flow, designer, clock, monkeypatch):
    ready_design(flow, designer)
    Metering.objects.filter(pk=flow.pk).update(manager=None)
    calls = []
    real = M.default_manager
    monkeypatch.setattr(M, "default_manager", lambda: calls.append(1) or real())
    reminders(clock, datetime(2026, 11, 4, 12, 0))
    assert len(calls) == 1


def test_early_deadline_is_late_then_overdue_next_morning(flow, designer, clock, bot_events):
    quiet_price(flow)
    from metering.design.models import Design

    Design.objects.filter(pk=flow.design.pk).update(
        due_at=datetime(2026, 11, 3, 14, 0), assigned_at=datetime(2026, 11, 3, 13, 0)
    )
    Design.objects.filter(pk=flow.design.pk).update(due_at=datetime(2026, 11, 5, 8, 0))
    assert reminders(clock, datetime(2026, 11, 5, 8, 0))["late"] == 1
    assert reminders(clock, datetime(2026, 11, 5, 9, 0))["overdue"] == 0  # same day
    assert reminders(clock, datetime(2026, 11, 5, 18, 0))["overdue"] == 0
    assert reminders(clock, datetime(2026, 11, 6, 9, 0))["overdue"] == 1


def _load_backfill(app, name):
    import importlib

    from django.apps import apps

    mod = importlib.import_module(f"metering.{app}.migrations.{name}")
    return lambda: mod.backfill_stage(apps, None)


@pytest.mark.parametrize(
    "app,name,model_path",
    [
        ("design", "0010_offer_stage2_backfill", "metering.design.models.Design"),
        ("price", "0025_offer_stage2_backfill", "metering.price.models.Price"),
    ],
)
def test_backfill_of_unfinished_rows(app, name, model_path, operator, ali, default_factory):
    from datetime import date

    from django.utils.module_loading import import_string

    from order.models import Order

    Model = import_string(model_path)
    rows = {}
    for i, kind in enumerate(["sold", "cancelled", "ordered", "plain", "finished"]):
        inv = lead(operator, f"+99890222000{i}")
        m = M.create_metering(
            client=inv.client, date_time=WHEN, invoice=inv, author=operator, measurer=ali
        )
        rows[kind] = (m, Model.objects.create(metering=m, done=kind == "finished"))
    Metering.objects.filter(pk=rows["sold"][0].pk).update(status=MeteringStatus.sold_out)
    Metering.objects.filter(pk=rows["cancelled"][0].pk).update(status=MeteringStatus.dont_need)
    Order.objects.create(
        metering=rows["ordered"][0],
        client=rows["ordered"][0].client,
        reception_date=date(2026, 11, 3),
        address="x",
        factory=default_factory,
    )
    Metering.objects.filter(pk=rows["ordered"][0].pk).update(status=MeteringStatus.done)
    Model.objects.update(stage="work", done_at=None)

    _load_backfill(app, name)()

    got = {k: Model.objects.get(pk=row.pk) for k, (_, row) in rows.items()}
    assert {k: (r.stage, r.done) for k, r in got.items()} == {
        "sold": ("approved", True),
        "cancelled": ("cancelled", False),
        "ordered": ("approved", True),
        "plain": ("work", False),
        "finished": ("approved", True),
    }
    assert got["plain"].due_at is None and got["plain"].assigned_at == got["plain"].created_at


# ------------------------------------------------------------------ roles = groups
def test_designers_and_pricers_are_explicit_holders(make_staff, superuser):
    own = make_staff("oauth.user_design", "design.view_design", name="Own")
    grp = Group.objects.get(name="Dizayner")
    via_group = make_staff(name="Via group")
    via_group.groups.add(grp)
    plain = make_staff("design.view_design")
    assert set(M.designers()) == {own, via_group}
    assert superuser not in set(M.designers()) and plain not in set(M.designers())
    narx = make_staff(name="Narx via group")
    narx.groups.add(Group.objects.get(name="Menejer"))  # the managers calculate the price
    assert list(M.pricers()) == [narx]
    assert superuser not in set(M.pricers())
    # a superuser with the explicit flag is a designer
    superuser.user_permissions.add(Permission.objects.get(codename="user_design"))
    assert superuser in set(M.designers())


def test_group_members_with_telegram_get_the_tasks(
    operator, ali, pricer, manager, make_staff, bot_events
):
    designer = make_staff(name="Roli", telegram_id=9100)
    designer.groups.add(Group.objects.get(name="Dizayner"))
    bot_events.clear()
    finished(operator, ali, designer, pricer, manager)
    got = {e["task"]["kind"]: e for e in bot_events.of("offer.assigned")}
    assert got["design"]["to"] == [9100]


def test_routing_helpers_by_group(make_staff, superuser):
    from oauth.services import staff_with_permission

    def member(group, **kw):
        u = make_staff(**kw)
        u.groups.add(Group.objects.get(name=group))
        return u

    mz = member("O'lcham oluvchi")
    mn = member("Menejer")
    ret = member("Bosh menejer")
    assert mz in M.measurers() and superuser not in M.measurers()
    assert mn in M.managers() and superuser not in M.managers()
    assert ret.has_perm("metering.manage_metering")
    for group, codename in (
        ("Konstruktor", "user_detailing"),
        ("Rover", "user_rover"),
        ("Molyar", "user_painter"),
        ("Sborkachi", "user_assembly"),
    ):
        u = member(group)
        found = set(staff_with_permission(codename))
        assert u in found and superuser not in found
    off = member("Konstruktor", is_active=False)
    assert off not in set(staff_with_permission("user_detailing"))


def test_pipeline_overview(
    flow, designer, pricer, manager, ali, clock, django_assert_max_num_queries
):
    from metering.design.models import Design

    Design.objects.filter(pk=flow.design.pk).update(due_at=datetime(2026, 11, 3, 9, 0))
    with django_assert_max_num_queries(18):
        out = M.pipeline_overview(NOW)
    c = out["counts"]
    assert (c["design_work"], c["design_overdue"], c["price_work"], c["price_overdue"]) == (
        1,
        1,
        1,
        0,
    )
    assert c["zamer_waiting"] == 0 and c["order_ready"] == 0
    row = out["overdue"][0]
    assert (
        row["kind"] == "design"
        and row["id"] == flow.design.pk
        and row["person"]["id"] == designer.pk
    )
    assert row["late_hours"] == 3.0 and row["url"] == f"/designs/{flow.design.pk}"
    load = {(r["role"], r["person"]["id"]): r for r in out["load"]}
    assert (
        load[("dizayner", designer.pk)]["open"] == 1
        and load[("dizayner", designer.pk)]["overdue"] == 1
    )
    assert load[("narxchi", pricer.pk)]["open"] == 1
    ready_design(flow, designer)
    load = {(r["role"], r["person"]["id"]): r for r in M.pipeline_overview(NOW)["load"]}
    assert load[("menejer", manager.pk)]["open"] == 1


# ------------------------------------------------------------------ owner's rule: no «Narxchi»
def price_manager(make_staff, **extra):
    """A manager who also calculates the price (Menejer lavozimi after oauth 0013)."""
    return make_staff(
        "metering.present_to_client", "metering.view_metering",
        "price.view_price", "price.change_price", **extra,
    )  # fmt: skip


def test_finish_gives_the_price_to_the_chosen_manager(operator, ali, designer, make_staff):
    """No pricer is picked: the price goes to the manager; the only designer is preselected."""
    mgr = price_manager(make_staff, name="Menejer", telegram_id=9200)
    price_manager(make_staff, name="Bosh menejer")  # two managers: the measurer chooses
    m = finished(operator, ali, None, None, mgr, step="price")
    assert m.price.user == mgr and m.manager == mgr
    inv = lead(operator, "+998901112299")
    m2 = M.create_metering(
        client=inv.client, date_time=WHEN, invoice=inv, author=operator, measurer=ali
    )
    M.mark_metering_measured(m2, by=ali)
    upload_file(m2)
    M.finish_metering(m2, by=ali, note="ok", next_step="design_price", manager=mgr)
    m2 = Metering.objects.get(pk=m2.pk)
    assert m2.design.user == designer and m2.price.user == mgr


def test_finish_refuses_a_manager_without_price_rights(operator, ali, manager):
    with pytest.raises(ServiceError) as e:
        finished(operator, ali, None, None, manager, step="price")
    assert e.value.field == "manager"


def test_the_boss_gets_a_copy_of_the_managers_cards(
    operator, ali, designer, make_staff, bot_events
):
    boss = make_staff("metering.manage_metering", "metering.view_metering", telegram_id=9300)
    mgr = price_manager(make_staff, name="Menejer", telegram_id=9200)
    bot_events.clear()
    m = finished(operator, ali, designer, None, mgr)
    by_kind = {e["task"]["kind"]: e for e in bot_events.of("offer.assigned")}
    # owner: not too many messages for the boss - no copies of the task cards
    assert by_kind["price"]["to"] == [9200]
    assert by_kind["design"]["to"] == [9001]
    # design ready: the «tayyor» card goes to the manager and the boss
    bot_events.clear()
    ready_design(m, designer)
    assert bot_events.one("offer.present")["to"] == [9200, 9300]
    # the daily «no answer yet» reminder goes to the manager only
    later = NOW + timedelta(days=2)
    M.due_offer_reminders(later.replace(hour=10))
    assert [e["to"] for e in bot_events.of("offer.present") if e["how"] == "reminder"] == [[9200]]
    # the boss answers in the bot: the manager's copy is closed too
    bot_events.clear()
    DS.record_design_answer(m.design, by=boss, answer="approved")
    assert bot_events.one("offer.changed")["to"] == [9200, 9300]
    # price ready + agreed: the boss is told to make the order
    PS.mark_price_done(m.price, by=mgr)
    bot_events.clear()
    PS.record_price_answer(m.price, by=mgr, answer="approved")
    assert 9300 in bot_events.one("offer.order_ready")["to"]


def test_admin_gives_old_unassigned_prices_to_a_manager(
    flow, pricer, admin_api, api, bot_events
):
    """Prices from before the managers got the price job: nobody calculates them. The
    admin gives them (oldest first, N of them) to a manager with a deadline."""
    from metering.price.models import Price

    Price.objects.filter(metering=flow).update(user=None, due_at=None)
    Metering.objects.filter(pk=flow.pk).update(manager=None)
    loose = Price.objects.create(desc="O'lchovsiz", stage="work")
    url = "/api/v1/prices/assign/"
    assert admin_api.get(url).data == {"unassigned": 2}
    body = {"user": pricer.pk, "due_at": "2026-11-05T18:00:00", "count": 1}
    assert api("price.view_price", "price.add_price").post(url, body, format="json").status_code == 400
    bot_events.clear()
    r = admin_api.post(url, body, format="json")
    assert r.status_code == 200, r.data
    assert r.data == {"assigned": 1, "left": 1}  # the oldest: the zamer's price
    p = Price.objects.get(metering=flow)
    assert p.user_id == pricer.pk and p.due_at == datetime(2026, 11, 5, 18, 0)
    assert Metering.objects.get(pk=flow.pk).manager_id == pricer.pk  # «tayyor» comes back
    ev = bot_events.one("offer.assigned")
    assert ev["to"] == [9002] and ev["task"]["id"] == p.pk
    r = admin_api.post(url, {**body, "count": None}, format="json")
    assert r.data == {"assigned": 1, "left": 0}
    assert Price.objects.get(pk=loose.pk).user_id == pricer.pk


def test_admin_deletes_old_unassigned_prices(flow, pricer, admin_api, api):
    """Only the admin; only prices nobody calculates; a sold zamer's price stays."""
    from metering.price.models import Price

    Price.objects.filter(metering=flow).update(user=None)
    old = Price.objects.create(desc="eski", stage="work")
    taken = Price.objects.create(desc="ishda", stage="work", user=pricer)
    rows = admin_api.get("/api/v1/prices/unassigned/").data
    assert {r["id"] for r in rows} == {flow.price.pk, old.pk}
    url = "/api/v1/prices/unassigned/delete/"
    staff = api("price.view_price", "price.add_price", "price.change_price")
    assert staff.get("/api/v1/prices/unassigned/").status_code == 403
    assert staff.post(url, {"ids": [old.pk]}, format="json").status_code == 400
    r = admin_api.post(url, {"ids": [old.pk, taken.pk]}, format="json")
    assert r.status_code == 200 and r.data == {"deleted": 1, "kept": 1}
    assert not Price.objects.filter(pk=old.pk).exists() and Price.objects.filter(pk=taken.pk).exists()
    assert admin_api.post(url, {"ids": "x"}, format="json").status_code == 400
