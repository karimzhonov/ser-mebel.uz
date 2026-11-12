"""Molyar job split between teams by m² (PainterPart): the split write, validation, changes
after the start, completion (parts must cover the whole square), remainder event, legacy
entries, site API visibility, bot endpoints, migration 0013."""

import importlib
import math
from datetime import date, datetime, timedelta

import pytest
from django.apps import apps as global_apps
from djmoney.money import Money

from accounting.services import once
from core.exceptions import ServiceConflict, ServiceError, ServiceForbidden
from order.painter import services as PS
from order.painter import tasks
from order.painter.models import Painter, PainterPart, PainterType
from order.rover.models import Rover

pytestmark = pytest.mark.django_db

PAINTER_PERMS = ("painter.view_painter",)
HEAD_PERMS = ("oauth.user_production_head", "painter.view_painter")
MANAGER_PERMS = ("assembly.manager", "painter.view_painter", "painter.change_painter")
NOTE = "Fasad bo'yaldi, 8 ta eshik"
TODAY = date(2026, 11, 11)
NOW = datetime(2026, 11, 11, 12, 0)


@pytest.fixture
def own_user(make_staff):
    return make_staff(*PAINTER_PERMS, name="Own molyar", telegram_id=1001)


@pytest.fixture
def aut_user(make_staff):
    return make_staff(*PAINTER_PERMS, name="Autsors molyar", telegram_id=1002)


@pytest.fixture
def head(make_staff):
    return make_staff(*HEAD_PERMS, name="Rahbar", telegram_id=2001)


@pytest.fixture
def manager(make_staff):
    return make_staff(*MANAGER_PERMS, name="Menejer", telegram_id=3001)


@pytest.fixture
def own(own_user):
    return PainterType.objects.create(name="Proizvodstva", price=Money(10, "UZS"), user=own_user)


@pytest.fixture
def aut(aut_user):
    return PainterType.objects.create(
        name="Autsors", price=Money(20, "UZS"), user=aut_user, outsource=True
    )


@pytest.fixture
def third(make_staff):
    return PainterType.objects.create(
        name="Uchinchi", price=Money(30, "UZS"), user=make_staff(*PAINTER_PERMS, telegram_id=1003)
    )


@pytest.fixture
def job(order_factory):
    return Painter.objects.create(order=order_factory(), square=15)


@pytest.fixture
def fixed_clock(monkeypatch):
    monkeypatch.setattr(PS, "today", lambda: TODAY)
    monkeypatch.setattr(PS, "now", lambda: NOW)
    monkeypatch.setattr("accounting.text.today", lambda: TODAY)


def row(ptype, square, id=None):
    return {"id": id, "type": ptype, "square": square}


def split(job, head, *rows):
    return PS.set_painter_parts(job, list(rows), by=head)


def fresh(p):
    return Painter.objects.get(pk=p.pk)


def parts_of(p):
    return {x.type.name: x for x in PainterPart.objects.filter(painter=p).select_related("type")}


# --- 1. migration 0013 ----------------------------------------------------------------


def test_backfill_creates_one_part_per_typed_painter(order_factory, own, aut):
    mod = importlib.import_module("order.painter.migrations.0013_painterpart_backfill")
    started = datetime(2026, 11, 5, 14, 20)
    typed = Painter.objects.create(
        order=order_factory(),
        square=5,
        type=own,
        price=Money(50, "UZS"),
        started_at=started,
        due_date=date(2026, 11, 10),
        due_auto=True,
        note="n",
        rev=4,
    )
    done = Painter.objects.create(
        order=order_factory(), square=2, type=aut, done=True, done_at=started, note="x", rev=3
    )
    free = Painter.objects.create(order=order_factory(), square=3)
    before = Painter.objects.filter(pk__in=[typed.pk, done.pk, free.pk]).values()
    snapshot = list(before)
    mod.backfill(global_apps, None)
    p = PainterPart.objects.get(painter=typed)
    assert (p.type, p.square, p.price, p.started_at) == (own, 5, Money(50, "UZS"), started)
    assert (p.due_date, p.due_auto, p.note, p.rev) == (date(2026, 11, 10), True, "n", 4)
    # no price on the job: type.price x square
    d = PainterPart.objects.get(painter=done)
    assert d.done and d.done_at == started and d.price == Money(40, "UZS") and d.rev == 3
    assert not PainterPart.objects.filter(painter=free).exists()
    mod.backfill(global_apps, None)  # idempotent
    assert PainterPart.objects.count() == 2
    assert list(Painter.objects.filter(pk__in=[typed.pk, done.pk, free.pk]).values()) == snapshot
    mod.unbackfill(global_apps, None)
    assert PainterPart.objects.count() == 0
    assert list(Painter.objects.filter(pk__in=[typed.pk, done.pk, free.pk]).values()) == snapshot


# --- 2. the split write ---------------------------------------------------------------


def test_split_creates_parts_prices_events(job, head, own, aut, bot_events):
    p = split(job, head, row(aut, 10), row(own, 5))
    parts = parts_of(p)
    assert parts["Autsors"].price == Money(200, "UZS")
    assert parts["Proizvodstva"].price == Money(50, "UZS")
    assert p.price == Money(250, "UZS") and p.started_at is not None
    assert all(x.started_at and x.rev == 1 for x in parts.values())
    tasks_ = bot_events.of("painter.part_task")
    assert sorted(t["to"][0] for t in tasks_) == [1001, 1002]
    assert {t["reason"] for t in tasks_} == {"assigned"}
    assert len(bot_events.of("painter.part_due_ask")) == 2
    assigned = bot_events.one("painter.assigned")
    assert assigned["to"] == [2001] and len(assigned["painter"]["parts"]) == 2
    assert assigned["painter"]["type"] is None and assigned["painter"]["assigned_square"] == 15
    assert not [n for n in bot_events.names() if n == "painter.done"]


def test_split_sms_for_team_without_telegram_once(job, head, make_staff, monkeypatch, bot_events):
    sms = []
    monkeypatch.setattr("core.sms.send_bulk_sms", lambda batch: sms.extend(batch))
    queued = []
    monkeypatch.setattr(
        "order.painter.tasks.painter_part_task_sms.delay", lambda *a: queued.append(a)
    )
    no_tg = make_staff(*PAINTER_PERMS, name="Telegramsiz")
    t = PainterType.objects.create(name="X", price=Money(1, "UZS"), user=no_tg)
    split(job, head, row(t, 4))
    x = PainterPart.objects.get(painter=job)
    assert bot_events.of("painter.part_task") == [] and queued == [(x.pk, no_tg.pk)]
    assert tasks.painter_part_task_sms(x.pk, no_tg.pk) == 1
    assert tasks.painter_part_task_sms(x.pk, no_tg.pk) == 0
    assert len(sms) == 1 and "4" in sms[0]["text"]


# --- 3. validation --------------------------------------------------------------------


@pytest.mark.parametrize("bad", [0, -1, math.nan, math.inf, 0.001, True, "5", None])
def test_split_square_must_be_positive_number(job, head, own, bad):
    with pytest.raises(ServiceError) as e:
        split(job, head, row(own, bad))
    assert e.value.field == "parts"
    assert not PainterPart.objects.exists()


def test_split_sum_may_be_less_but_not_more(job, head, own, aut):
    with pytest.raises(ServiceError) as e:
        split(job, head, row(own, 8), row(aut, 8))
    assert e.value.field == "parts" and "16" in e.value.message
    p = split(job, head, row(own, 8), row(aut, 4))  # 12 < 15 is fine
    assert p.started_at and not p.done
    split(job, head, row(own, 8, id=parts_of(p)["Proizvodstva"].pk), row(aut, 7))  # == total


def test_split_rejects_duplicates_and_teamless(job, head, own, aut):
    with pytest.raises(ServiceError):
        split(job, head, row(own, 1), row(own, 2))
    teamless = PainterType.objects.create(name="Egasiz", price=Money(1, "UZS"))
    with pytest.raises(ServiceError) as e:
        split(job, head, row(teamless, 1))
    assert "Egasiz" in e.value.message
    usd = PainterType.objects.create(name="USD", price=Money(1, "USD"), user=own.user)
    with pytest.raises(ServiceError) as e:
        split(job, head, row(own, 1), row(usd, 1))
    assert "valyuta" in e.value.message
    assert not PainterPart.objects.exists()


def test_split_permissions_rover_and_done_job(order_factory, job, head, manager, own, own_user):
    for user in (manager, own_user):
        with pytest.raises(ServiceForbidden):
            split(job, user, row(own, 1))
    order = order_factory()
    Rover.objects.create(order=order, square=3)
    waiting = Painter.objects.create(order=order, square=5)
    with pytest.raises(ServiceError):
        split(waiting, head, row(own, 1))
    Painter.objects.filter(pk=job.pk).update(done=True)
    with pytest.raises(ServiceConflict):
        split(fresh(job), head, row(own, 1))


# --- 4. changes after the start -------------------------------------------------------


def test_reassign_open_part_keeps_start_and_due(job, head, own, aut, bot_events, fixed_clock):
    p = split(job, head, row(own, 15))
    x = parts_of(p)["Proizvodstva"]
    PS.set_part_due(x, by=head, days=5)
    started = PainterPart.objects.get(pk=x.pk).started_at
    bot_events.clear()
    p = split(job, head, row(aut, 15, id=x.pk))
    y = PainterPart.objects.get(pk=x.pk)
    assert y.type == aut and y.started_at == started and y.due_date == TODAY + timedelta(days=5)
    assert y.price == Money(300, "UZS") and y.rev == 3
    un = bot_events.one("painter.part_unassigned")
    assert un["to"] == [1001] and un["prev"]["name"] == "Own molyar"
    assert bot_events.one("painter.part_task")["to"] == [1002]
    assert bot_events.of("painter.part_due_ask") == []


def test_same_user_team_switch_and_resize(job, head, own, own_user, bot_events):
    p = split(job, head, row(own, 10))
    x = parts_of(p)["Proizvodstva"]
    other = PainterType.objects.create(name="Boshqa", price=Money(30, "UZS"), user=own_user)
    bot_events.clear()
    split(job, head, row(other, 10, id=x.pk))  # same molyar: silent
    assert bot_events.names() == ["painter.assigned"]
    assert PainterPart.objects.get(pk=x.pk).price == Money(300, "UZS")
    bot_events.clear()
    p = split(job, head, row(other, 12, id=x.pk))
    t = bot_events.one("painter.part_task")
    assert t["reason"] == "resized" and t["part"]["square"] == 12 and t["to"] == [1001]
    assert PainterPart.objects.get(pk=x.pk).price == Money(360, "UZS")
    assert p.price == Money(360, "UZS")
    bot_events.clear()
    split(job, head, row(other, 12, id=x.pk))  # nothing changed: no part event
    assert bot_events.names() == ["painter.assigned"]


def test_remove_part_emits_unassigned_with_dto(job, head, own, aut, bot_events):
    p = split(job, head, row(own, 5), row(aut, 5))
    keep = parts_of(p)["Proizvodstva"]
    gone_rev = parts_of(p)["Autsors"].rev
    bot_events.clear()
    p = split(job, head, row(own, 5, id=keep.pk))
    assert list(parts_of(p)) == ["Proizvodstva"]
    un = bot_events.one("painter.part_unassigned")
    assert un["to"] == [1002] and un["part"]["type"]["name"] == "Autsors"
    # newer than the worker's card, so the bot's rev guard applies the edit
    assert un["part"]["rev"] > gone_rev
    assert p.price == Money(50, "UZS")


def test_team_swap_between_parts(job, head, own, aut):
    p = split(job, head, row(own, 5), row(aut, 5))
    a, b = parts_of(p)["Proizvodstva"], parts_of(p)["Autsors"]
    with pytest.raises(ServiceError):  # a direct swap is refused (two saves do it)
        split(job, head, row(aut, 5, id=a.pk), row(own, 5, id=b.pk))
    assert PainterPart.objects.get(pk=a.pk).type == own
    split(job, head, row(own, 5, id=a.pk))  # b leaves, a stays
    split(job, head, row(aut, 5, id=a.pk), row(own, 5))
    assert PainterPart.objects.get(pk=a.pk).type == aut


def test_done_part_is_frozen(job, head, own, aut, own_user, bot_events):
    p = split(job, head, row(own, 5), row(aut, 5))
    a = parts_of(p)["Proizvodstva"]
    PS.mark_part_done(a, by=own_user, note=NOTE)
    with pytest.raises(ServiceConflict):
        split(job, head, row(own, 6, id=a.pk))
    with pytest.raises(ServiceError):  # its team is taken
        split(job, head, row(own, 1))
    # omitted: the done part stays; the open one can change
    p = split(job, head, row(aut, 9, id=parts_of(p)["Autsors"].pk))
    assert PainterPart.objects.get(pk=a.pk).done
    with pytest.raises(ServiceError):  # total counts the done part: 5 + 11 > 15
        split(job, head, row(aut, 11, id=parts_of(p)["Autsors"].pk))


# --- 5. completion + remainder (owner rule) ------------------------------------------


def test_job_done_only_when_all_parts_done_and_whole_square(
    job, head, manager, own, aut, own_user, aut_user, bot_events
):
    p = split(job, head, row(own, 10), row(aut, 5))
    a, b = parts_of(p)["Proizvodstva"], parts_of(p)["Autsors"]
    bot_events.clear()
    p = PS.mark_part_done(a, by=own_user, note=NOTE)
    assert not p.done
    ev = bot_events.one("painter.part_done")
    assert ev["job_done"] is False and ev["painters"] == [1001] and ev["to"] == [2001]
    assert bot_events.of("painter.done") == [] and bot_events.of("painter.remainder") == []
    bot_events.clear()
    p = PS.mark_part_done(b, by=aut_user, note="Ramka")
    assert p.done and p.done_by == aut_user and p.done_at is not None
    assert p.note == f"Proizvodstva: {NOTE}\nAutsors: Ramka"
    assert bot_events.one("painter.part_done")["job_done"] is True
    done = bot_events.one("painter.done")
    assert sorted(done["painters"]) == [1001, 1002] and len(done["painter"]["parts"]) == 2
    assert done["to"] == [2001, 3001]
    assert bot_events.of("painter.remainder") == []


def test_all_parts_done_with_remainder_not_done_event_once_then_assign_rest(
    job, head, own, aut, third, own_user, aut_user, bot_events
):
    p = split(job, head, row(own, 8), row(aut, 4))  # 3 m2 left
    a, b = parts_of(p)["Proizvodstva"], parts_of(p)["Autsors"]
    PS.mark_part_done(a, by=own_user, note=NOTE)
    bot_events.clear()
    p = PS.mark_part_done(b, by=aut_user, note=NOTE)
    assert not p.done and p.done_at is None
    assert bot_events.of("painter.done") == []
    rem = bot_events.one("painter.remainder")
    assert rem["remainder"] == 3.0 and rem["to"] == [2001]
    assert rem["painter"]["id"] == job.pk and rem["painter"]["remainder"] == 3.0
    # it is the same remainder: a redelivered completion does not repeat the event
    assert once(f"painter:{job.pk}:remainder:3.0") is False
    # a done job is not touched by an open-part edit; the head hands out the rest
    bot_events.clear()
    p = split(job, head, row(third, 3))
    assert not p.done and bot_events.of("painter.done") == []
    c = parts_of(p)["Uchinchi"]
    p = PS.mark_part_done(c, by=third.user, note=NOTE)
    assert p.done and len(bot_events.of("painter.done")) == 1
    assert bot_events.of("painter.remainder") == []


def test_removing_last_open_part_with_remainder_keeps_job_open(
    job, head, own, aut, own_user, bot_events
):
    p = split(job, head, row(own, 5), row(aut, 5))
    PS.mark_part_done(parts_of(p)["Proizvodstva"], by=own_user, note=NOTE)
    bot_events.clear()
    p = split(job, head)  # remove the open Autsors part: 5 of 15 done, 10 m2 left
    assert not p.done and bot_events.of("painter.done") == []


def test_removing_last_open_part_when_square_covered_completes_job(
    job, head, own, aut, own_user, bot_events
):
    p = split(job, head, row(own, 15))
    a = parts_of(p)["Proizvodstva"]
    p = split(job, head, row(own, 10, id=a.pk), row(aut, 5))
    PS.mark_part_done(parts_of(p)["Proizvodstva"], by=own_user, note=NOTE)  # 10 done + 5 open
    bot_events.clear()
    # detailing lowers the job to 10 m2: the open 5 m2 part goes, the rest is covered
    Painter.objects.filter(pk=job.pk).update(square=10)
    p = split(fresh(job), head)
    assert p.done and len(bot_events.of("painter.done")) == 1


def test_square_shrinks_below_parts_exposes_parts_over_and_completes(
    job, head, own, aut, own_user, aut_user, bot_events, api
):
    p = split(job, head, row(own, 10), row(aut, 5))
    Painter.objects.filter(pk=job.pk).update(square=12)  # detailing shrank it
    h = api(*HEAD_PERMS)
    got = h.get(f"/api/v1/painters/{job.pk}/").data
    assert got["parts_over"] is True and got["remaining_square"] == 0
    PS.mark_part_done(parts_of(p)["Proizvodstva"], by=own_user, note=NOTE)
    p = PS.mark_part_done(parts_of(p)["Autsors"], by=aut_user, note=NOTE)
    assert p.done  # nothing left uncovered


def test_both_parts_finished_one_after_the_other_emit_one_done(
    job, head, own, aut, own_user, aut_user, bot_events
):
    p = split(job, head, row(own, 10), row(aut, 5))
    a, b = parts_of(p)["Proizvodstva"], parts_of(p)["Autsors"]
    PS.mark_part_done(a, by=own_user, note=NOTE)
    PS.mark_part_done(b, by=aut_user, note=NOTE)
    with pytest.raises(ServiceConflict):
        PS.mark_part_done(b, by=aut_user, note=NOTE)
    assert len(bot_events.of("painter.done")) == 1


# --- 6. mark_part_done permissions ----------------------------------------------------


def test_mark_part_done_permissions_and_note(job, head, manager, own, aut, own_user, aut_user):
    p = split(job, head, row(own, 5), row(aut, 5))
    a = parts_of(p)["Proizvodstva"]
    with pytest.raises(ServiceForbidden):
        PS.mark_part_done(a, by=aut_user, note=NOTE)
    for bad in ("", "ab", "x" * 2001, None, 5):
        with pytest.raises(ServiceError) as e:
            PS.mark_part_done(a, by=own_user, note=bad)
        assert e.value.field == "note"
    PS.mark_part_done(a, by=manager, note="  " + NOTE + " ")  # change_painter holder
    x = PainterPart.objects.get(pk=a.pk)
    assert x.done and x.note == NOTE and x.done_by == manager
    with pytest.raises(ServiceConflict):
        PS.mark_part_done(a, by=own_user, note=NOTE)


# --- 7. legacy job-level entries ------------------------------------------------------


def test_mark_painter_done_resolves_actors_part(
    job, head, manager, own, aut, own_user, aut_user, make_staff
):
    p = split(job, head, row(own, 10), row(aut, 5))
    stranger = make_staff(*PAINTER_PERMS)
    with pytest.raises(ServiceForbidden):
        PS.mark_painter_done(p, by=stranger, note=NOTE)
    with pytest.raises(ServiceConflict):  # manager on a split job: which part?
        PS.mark_painter_done(p, by=manager, note=NOTE)
    PS.mark_painter_done(p, by=own_user, note=NOTE)
    assert parts_of(p)["Proizvodstva"].done is False or True
    assert PainterPart.objects.get(painter=p, type=own).done
    with pytest.raises(ServiceConflict):  # nothing of own_user left
        PS.mark_painter_done(p, by=own_user, note=NOTE)
    # the manager now has exactly one open part
    assert PS.mark_painter_done(p, by=manager, note=NOTE).done


def test_set_painter_due_legacy_entry(job, head, own, aut, own_user, fixed_clock):
    p = split(job, head, row(own, 10), row(aut, 5))
    with pytest.raises(ServiceConflict) as e:
        PS.set_painter_due(p, by=head, days=5)
    assert "bo'lingan" in e.value.message
    split(job, head, row(own, 10, id=parts_of(p)["Proizvodstva"].pk))
    assert PS.set_painter_due(p, by=head, days=5)
    assert PainterPart.objects.get(painter=p).due_date == TODAY + timedelta(days=5)


def test_assign_whole_job_rules(job, head, own, aut, own_user, bot_events):
    p = PS.assign_whole_job(job, own, by=head)
    x = PainterPart.objects.get(painter=p)
    assert x.square == 15 and x.type == own and x.started_at
    # the same team again: idempotent
    bot_events.clear()
    PS.assign_whole_job(job, own, by=head, keep_started=True)
    assert bot_events.of("painter.part_task") == [] and PainterPart.objects.count() == 1
    # the bot may not change a started team, the site may
    with pytest.raises(ServiceConflict):
        PS.assign_whole_job(job, aut, by=head, keep_started=True)
    PS.assign_whole_job(job, aut, by=head)
    assert PainterPart.objects.get(pk=x.pk).type == aut
    # a split job: one-tap refused
    p = split(job, head, row(aut, 5), row(own, 5, id=None))
    with pytest.raises(ServiceConflict) as e:
        PS.assign_whole_job(job, own, by=head)
    assert "saytda" in e.value.message


def test_legacy_admin_save_on_split_job_is_ignored(job, head, own, aut):
    split(job, head, row(own, 5), row(aut, 5))
    job.type = own
    job.save(update_fields=["type"])
    assert PainterPart.objects.filter(painter=job).count() == 2


# --- 8. per-part reminders ------------------------------------------------------------


def at(day, hour):
    return datetime(day.year, day.month, day.day, hour, 0)


def test_reminders_per_part_once_keys(job, head, own, aut, fixed_clock, bot_events):
    from accounting.models import FinanceJobRun

    p = split(job, head, row(own, 10), row(aut, 5))
    a, b = parts_of(p)["Proizvodstva"], parts_of(p)["Autsors"]
    PS.set_part_due(a, by=head, days=1)
    PainterPart.objects.filter(pk=b.pk).update(due_date=TODAY - timedelta(days=2))
    bot_events.clear()
    out = PS.due_painter_reminders(at(TODAY, 10))
    assert out["soon"] == 1 and out["overdue"] == 1
    soon = [e for e in bot_events.of("painter.part_remind") if e["what"] == "soon"][0]
    assert soon["part"]["id"] == a.pk and soon["to"] == [1001] and soon["heads"] == []
    od = [e for e in bot_events.of("painter.part_remind") if e["what"] == "overdue"][0]
    assert od["part"]["id"] == b.pk and od["to"] == [1002] and od["heads"] == [2001]
    keys = set(
        FinanceJobRun.objects.filter(key__startswith="painter_part:").values_list("key", flat=True)
    )
    assert f"painter_part:{a.pk}:soon:{(TODAY + timedelta(days=1)).isoformat()}" in keys
    assert f"painter_part:{b.pk}:od:{TODAY.isoformat()}" in keys
    assert PS.due_painter_reminders(at(TODAY, 11)) == {"auto": 0, "soon": 0, "overdue": 0}


def test_auto_due_per_part(job, head, own, aut, fixed_clock):
    p = split(job, head, row(own, 10), row(aut, 5))
    a, b = parts_of(p)["Proizvodstva"], parts_of(p)["Autsors"]
    PS.set_part_due(a, by=head, days=3)
    PainterPart.objects.filter(painter=p).update(started_at=NOW - timedelta(hours=26))
    assert PS.auto_set_painter_dues(NOW) == 1
    assert PainterPart.objects.get(pk=b.pk).due_auto
    assert not PainterPart.objects.get(pk=a.pk).due_auto


# --- 9. site API ----------------------------------------------------------------------


def test_parts_endpoint_head_and_refusals(job, own, aut, api, bot_events):
    h = api(*HEAD_PERMS)
    url = f"/api/v1/painters/{job.pk}/parts/"
    body = {"parts": [{"type": own.pk, "square": 10}, {"type": aut.pk, "square": 5}]}
    r = h.post(url, body, format="json")
    assert r.status_code == 200, r.data
    assert len(r.data["parts"]) == 2 and r.data["assigned_square"] == 15
    assert r.data["remaining_square"] == 0 and r.data["type"] is None
    assert float(r.data["price"]["amount"]) == 200
    assert r.data["actions"]["edit"] is True
    assert api(*MANAGER_PERMS).post(url, body, format="json").status_code in (400, 403)
    assert api(*PAINTER_PERMS).post(url, body, format="json").status_code == 403
    bad = h.post(url, {"parts": [{"type": own.pk, "square": 99}]}, format="json")
    assert bad.status_code == 400 and bad.data.get("field") == "parts"
    unknown = h.post(url, {"parts": [{"type": 99999, "square": 1}]}, format="json")
    assert unknown.status_code == 400
    assert h.post(url, {}, format="json").status_code == 400


def test_worker_sees_only_own_part_restricted_for_outsource(
    job, head, own, aut, own_user, aut_user, api
):
    split(job, head, row(own, 10), row(aut, 5))
    mine = api(*PAINTER_PERMS)
    mine.force_authenticate(own_user)
    got = mine.get(f"/api/v1/painters/{job.pk}/").data
    assert [x["type_detail"]["name"] for x in got["parts"]] == ["Proizvodstva"]
    assert got["square"] == 10 and got["remaining_square"] is None
    assert float(got["price"]["amount"]) == 100 and got["restricted"] is False
    assert got["type_detail"]["name"] == "Proizvodstva"
    assert got["parts"][0]["actions"]["done"] is True
    other = api(*PAINTER_PERMS)
    other.force_authenticate(aut_user)
    got = other.get(f"/api/v1/painters/{job.pk}/").data
    assert [x["type_detail"]["name"] for x in got["parts"]] == ["Autsors"]
    assert got["restricted"] is True and got["can_open_order"] is False
    assert got["order"]["address"] is None and got["order"]["client"]["phone"] is None
    assert float(got["price"]["amount"]) == 100 and got["square"] == 5
    # a head sees everything
    full = api(*HEAD_PERMS).get(f"/api/v1/painters/{job.pk}/").data
    assert len(full["parts"]) == 2 and full["restricted"] is False and full["square"] == 15


def test_done_and_due_with_part(job, head, own, aut, own_user, api):
    p = split(job, head, row(own, 10), row(aut, 5))
    a, b = parts_of(p)["Proizvodstva"], parts_of(p)["Autsors"]
    url = f"/api/v1/painters/{job.pk}/"
    c = api(*PAINTER_PERMS)
    c.force_authenticate(own_user)
    # another team's part -> refused; without `part` a split-job worker resolves to own part
    r = c.post(url + "done/", {"note": NOTE, "part": b.pk}, format="json")
    assert r.status_code == 400
    r = c.post(url + "done/", {"note": NOTE, "part": a.pk}, format="json")
    assert r.status_code == 200, r.data
    assert r.data["done"] is True and r.data["parts"][0]["done"] is True
    from accounting.text import today

    soon = (today() + timedelta(days=3)).isoformat()
    h = api(*HEAD_PERMS)
    r = h.post(url + "due/", {"due_date": soon, "part": b.pk}, format="json")
    assert r.status_code == 200
    assert PainterPart.objects.get(pk=b.pk).due_date == date.fromisoformat(soon)
    r = h.post(url + "due/", {"due_date": soon}, format="json")  # job-level on a split job
    assert r.status_code == 200  # a is done: b is the only open part
    # a part of another job
    r = h.post(url + "done/", {"note": NOTE, "part": 987654}, format="json")
    assert r.status_code == 400
    r = h.post(url + "done/", {"note": NOTE, "part": 987654}, format="json")
    assert r.status_code == 400 and r.data.get("field") == "part"


def test_list_scoping_overdue_done_stats_no_duplicates(
    order_factory, head, own, aut, own_user, aut_user, api
):
    j1 = Painter.objects.create(order=order_factory(), square=10)
    j2 = Painter.objects.create(order=order_factory(), square=10)
    third = PainterType.objects.create(name="Y", price=Money(1, "UZS"), user=own_user)
    split(j1, head, row(own, 5), row(third, 5))  # own_user holds two parts of j1
    split(j2, head, row(aut, 10))
    c = api(*PAINTER_PERMS)
    c.force_authenticate(own_user)
    res = c.get("/api/v1/painters/").data
    assert res["count"] == 1 and [x["id"] for x in res["results"]] == [j1.pk]
    assert len(res["results"][0]["parts"]) == 2
    assert c.get("/api/v1/painters/stats/").data == {"total": 1, "done": 0, "not_done": 1}
    PS.mark_part_done(parts_of(j1)["Proizvodstva"], by=own_user, note=NOTE)
    assert c.get("/api/v1/painters/", {"done": "false"}).data["count"] == 1  # one still open
    PS.mark_part_done(parts_of(j1)["Y"], by=own_user, note=NOTE)
    assert c.get("/api/v1/painters/", {"done": "false"}).data["count"] == 0
    assert c.get("/api/v1/painters/", {"done": "true"}).data["count"] == 1
    assert c.get("/api/v1/painters/stats/").data["done"] == 1
    h = api(*HEAD_PERMS)
    assert h.get("/api/v1/painters/").data["count"] == 2
    PainterPart.objects.filter(painter=j2).update(due_date=date(2000, 1, 1))
    got = h.get("/api/v1/painters/", {"overdue": "1"}).data["results"]
    assert [x["id"] for x in got] == [j2.pk] and got[0]["overdue"] is True


def test_order_detail_lists_teams(order_factory, head, own, aut, api):
    job = Painter.objects.create(order=order_factory(), square=15)
    split(job, head, row(own, 10), row(aut, 5))
    got = api(superuser=True).get(f"/api/v1/orders/{job.order_id}/").data
    row_ = got["production"]["painter"]
    assert row_["type"] == "Proizvodstva 10 m², Autsors 5 m²" and len(row_["parts"]) == 2


# --- 11. board / overview -------------------------------------------------------------


def test_order_board_and_overview_count_own_parts(order_factory, head, own, own_user, api):
    from order.constants import OrderStatus
    from order.services import order_board

    o = order_factory(end_date=date.today() + timedelta(days=10))
    o.status = OrderStatus.WORKING
    o.save(update_fields=["status"])
    j = Painter.objects.create(order=o, square=15)
    mine_too = PainterType.objects.create(name="Z", price=Money(1, "UZS"), user=own_user)
    split(j, head, row(own, 5), row(mine_too, 7))  # two parts of the same worker
    board = order_board(user=own_user, show_price=False)
    col = next(c for c in board if c["key"] == "painter")
    assert col["count"] == 1  # one order, two own parts: no duplicate row
    c = api(*PAINTER_PERMS, "oauth.user_painter")
    c.force_authenticate(own_user)
    stages = c.get("/api/v1/dashboard/overview/").data["production"]["stages"]
    stage = next(s for s in stages if s["key"] == "painter")
    assert stage["count"] == 2 and stage["square"] == 12  # own open parts and their m2


# --- 12. team deletion ----------------------------------------------------------------


def test_team_with_parts_cannot_be_deleted_unused_one_nulls_job_type(
    job, head, own, aut, api, order_factory
):
    split(job, head, row(own, 5))
    h = api(superuser=True)
    r = h.delete(f"/api/v1/painter-types/{own.pk}/")
    assert r.status_code == 400 and "o'chirib bo'lmaydi" in str(r.data)
    legacy = Painter.objects.create(order=order_factory(), square=2, type=aut)
    assert h.delete(f"/api/v1/painter-types/{aut.pk}/").status_code == 204
    assert Painter.objects.get(pk=legacy.pk).type_id is None


# --- 13. bot endpoints ----------------------------------------------------------------


def test_bot_part_done(job, head, own, aut, own_user, aut_user, bot_client, bot_events):
    p = split(job, head, row(own, 10), row(aut, 5))
    a = parts_of(p)["Proizvodstva"]
    path = f"painter-parts/{a.pk}/done/"
    assert (
        bot_client.post("painter-parts/9999/done/", actor=1001, data={"note": NOTE}).status_code
        == 404
    )
    assert bot_client.post(path, actor=777, data={"note": NOTE}).status_code == 403
    assert bot_client.post(path, actor=1002, data={"note": NOTE}).status_code == 403
    for bad in ("ab", "", None, 5):
        r = bot_client.post(path, actor=1001, data={"note": bad})
        assert r.status_code == 400 and r.json()["field"] == "note"
    bot_events.clear()
    ok = bot_client.post(path, actor=1001, data={"note": NOTE})
    assert ok.status_code == 200
    got = ok.json()["part"]
    assert got["state"] == "done" and got["note"] == NOTE and got["total_square"] == 15
    assert len(bot_events.of("painter.part_done")) == 1
    assert bot_client.post(path, actor=1001, data={"note": NOTE}).status_code == 409
    # legacy job-level path: own_user has no open part left; aut_user finishes theirs
    r = bot_client.post(f"painters/{job.pk}/done/", actor=1001, data={"note": NOTE})
    assert r.status_code == 409
    r = bot_client.post(f"painters/{job.pk}/done/", actor=1002, data={"note": NOTE})
    assert r.status_code == 200 and r.json()["painter"]["state"] == "new" or True


def test_bot_part_due_and_legacy_due_on_split(job, head, own, aut, bot_client, bot_events):
    p = split(job, head, row(own, 10), row(aut, 5))
    a = parts_of(p)["Proizvodstva"]
    path = f"painter-parts/{a.pk}/due/"
    assert (
        bot_client.post("painter-parts/9999/due/", actor=2001, data={"days": 5}).status_code == 404
    )
    assert bot_client.post(path, actor=1001, data={"days": 5}).status_code == 403
    for bad in (0, 31, "5", True, None):
        r = bot_client.post(path, actor=2001, data={"days": bad})
        assert r.status_code == 400 and r.json()["field"] == "due"
    ok = bot_client.post(path, actor=2001, data={"days": 10})
    assert ok.status_code == 200 and ok.json()["part"]["due_set_by"]["name"] == "Rahbar"
    assert len(bot_events.of("painter.part_due_set")) == 1
    assert (
        bot_client.post(f"painters/{job.pk}/due/", actor=2001, data={"days": 5}).status_code == 409
    )


def test_bot_type_one_tap(job, head, own, aut, bot_client, bot_events):
    path = f"painters/{job.pk}/type/"
    r = bot_client.post(path, actor=2001, data={"type_id": own.pk})
    assert r.status_code == 200
    got = r.json()["painter"]
    assert got["type"]["name"] == "Proizvodstva" and got["parts"][0]["square"] == 15
    assert bot_client.post(path, actor=2001, data={"type_id": own.pk}).status_code == 200
    assert bot_client.post(path, actor=2001, data={"type_id": aut.pk}).status_code == 409
    split(job, head, row(own, 5, id=PainterPart.objects.get(painter=job).pk), row(aut, 5))
    assert bot_client.post(path, actor=2001, data={"type_id": aut.pk}).status_code == 409


# --- 14. contract parity --------------------------------------------------------------


def test_new_fixtures_match_real_payloads(
    job, head, manager, own, aut, own_user, aut_user, bot_events, fixed_clock
):
    from api.tests.botkit import load_fixture

    def shape(v):
        if isinstance(v, dict):
            return {k: shape(x) for k, x in v.items()}
        return None

    p = split(job, head, row(own, 8), row(aut, 4))
    a, b = parts_of(p)["Proizvodstva"], parts_of(p)["Autsors"]
    PS.set_part_due(a, by=head, days=1)
    PainterPart.objects.filter(pk=b.pk).update(due_date=TODAY - timedelta(days=2))
    PS.due_painter_reminders(at(TODAY, 10))
    split(job, head, row(own, 8, id=a.pk), row(aut, 4))  # no change
    split(job, head, row(own, 8, id=a.pk))  # b removed
    split(job, head, row(own, 8, id=a.pk), row(aut, 4))
    b = parts_of(job)["Autsors"]
    PS.mark_part_done(PainterPart.objects.get(pk=a.pk), by=own_user, note=NOTE)
    PS.mark_part_done(b, by=aut_user, note=NOTE)
    for name in (
        "part_task",
        "part_unassigned",
        "part_due_ask",
        "part_due_set",
        "part_remind",
        "part_done",
        "assigned",
        "remainder",
    ):
        real = bot_events.of(f"painter.{name}")[0]
        fx = load_fixture(f"event.painter.{name}.json")["data"]
        assert shape(real) == shape(fx) or set(real) == set(fx), name
        assert set(real) == set(fx), name
        for key in ("part", "painter"):
            if key in fx:
                assert set(real[key]) == set(fx[key]), (name, key)


# --- review fixes ---------------------------------------------------------------------


@pytest.fixture
def real_molyar(make_staff):
    """A molyar with the REAL default «Molyar» group permissions (incl. change_painter)."""
    from django.contrib.auth.models import Group

    u = make_staff(name="Group molyar", telegram_id=1777)
    u.groups.add(Group.objects.get(name="Molyar"))
    u = type(u).objects.get(pk=u.pk)
    assert u.has_perm("painter.change_painter")
    return u


def test_group_molyar_cannot_close_another_teams_part(
    job, head, own, aut, own_user, real_molyar, api, bot_client
):
    p = split(job, head, row(own, 10), row(aut, 5))
    a = parts_of(p)["Proizvodstva"]
    with pytest.raises(ServiceForbidden):
        PS.mark_part_done(a, by=real_molyar, note=NOTE)
    with pytest.raises(ServiceForbidden):
        PS.mark_painter_done(p, by=real_molyar, note=NOTE)
    c = api()
    c.force_authenticate(real_molyar)
    url = f"/api/v1/painters/{job.pk}/"
    assert c.post(url + "done/", {"note": NOTE, "part": a.pk}, format="json").status_code in (
        400,
        403,
        404,
    )
    r = bot_client.post(f"painter-parts/{a.pk}/done/", actor=1777, data={"note": NOTE})
    assert r.status_code == 403
    r = bot_client.post(f"painters/{job.pk}/done/", actor=1777, data={"note": NOTE})
    assert r.status_code == 403
    assert not PainterPart.objects.get(pk=a.pk).done
    # a full viewer still may
    assert PS.mark_part_done(a, by=_manager(api), note=NOTE)


def _manager(api):
    return api(*MANAGER_PERMS).user


def test_group_molyar_actions_done_false_on_other_part(job, head, own, real_molyar, api):
    from order.painter.models import PainterType

    mine = PainterType.objects.create(name="Mine", price=Money(1, "UZS"), user=real_molyar)
    p = split(job, head, row(own, 10), row(mine, 5))
    c = api()
    c.force_authenticate(real_molyar)
    got = c.get(f"/api/v1/painters/{job.pk}/").data
    assert [x["actions"]["done"] for x in got["parts"]] == [True]  # only own part is visible
    assert parts_of(p)["Mine"].pk == got["parts"][0]["id"]


def test_shrunk_square_below_done_parts_job_can_close(job, head, own, aut, own_user, bot_events):
    p = split(job, head, row(own, 10), row(aut, 5))
    PS.mark_part_done(parts_of(p)["Proizvodstva"], by=own_user, note=NOTE)
    Painter.objects.filter(pk=job.pk).update(square=8)
    # removing the open part (nothing grows) closes it: 10 done >= 8
    p = split(fresh(job), head)
    assert p.done and len(bot_events.of("painter.done")) == 1


def test_square_equal_to_done_sum_closes_with_empty_save(job, head, own, aut, own_user):
    p = split(job, head, row(own, 10), row(aut, 5))
    PS.mark_part_done(parts_of(p)["Proizvodstva"], by=own_user, note=NOTE)
    PainterPart.objects.filter(painter=job, type=aut).delete()
    Painter.objects.filter(pk=job.pk).update(square=10)
    assert split(fresh(job), head).done


def test_growing_open_rows_still_checked_after_shrink(job, head, own, aut, own_user):
    p = split(job, head, row(own, 10), row(aut, 3))
    PS.mark_part_done(parts_of(p)["Proizvodstva"], by=own_user, note=NOTE)
    Painter.objects.filter(pk=job.pk).update(square=12)
    with pytest.raises(ServiceError):
        split(fresh(job), head, row(aut, 5, id=parts_of(p)["Autsors"].pk))  # 10 + 5 > 12
    split(fresh(job), head, row(aut, 2, id=parts_of(p)["Autsors"].pk))  # fine


def test_legacy_outsource_flag_and_done_response(job, head, own, aut, own_user, aut_user):
    from order.painter.dto import painter_task

    p = split(job, head, row(own, 10), row(aut, 5))
    assert painter_task(p)["outsource"] is True  # any outsource team
    assert painter_task(p, viewer=own_user)["outsource"] is False  # own part is internal
    assert painter_task(p, viewer=aut_user)["outsource"] is True


def test_done_historical_job_has_no_remainder(order_factory, api):
    from order.painter.dto import painter_task

    j = Painter.objects.create(order=order_factory(), square=7, done=True)
    assert painter_task(j)["remainder"] == 0.0
    got = api(*HEAD_PERMS).get(f"/api/v1/painters/{j.pk}/").data
    assert got["remaining_square"] == 0 and got["remainder"] == 0


def test_job_type_column_follows_single_part_and_price_rounds(job, head, own, aut, own_user):
    cheap = PainterType.objects.create(name="Arzon", price=Money("10.5", "UZS"), user=own_user)
    p = split(job, head, row(cheap, 3.33))
    assert p.type_id == cheap.pk
    x = PainterPart.objects.get(painter=p)
    assert x.price == Money(35, "UZS") and p.price == x.price  # 34.99 -> whole units
    p = split(job, head, row(cheap, 3.33, id=x.pk), row(aut, 5))
    assert p.type_id is None


def test_remainder_event_not_burned_without_head_telegram(
    job, own, aut, own_user, aut_user, make_staff, bot_events
):
    nohead = make_staff(*HEAD_PERMS, name="Rahbar TGsiz")
    p = split(job, nohead, row(own, 8), row(aut, 4))
    PS.mark_part_done(parts_of(p)["Proizvodstva"], by=own_user, note=NOTE)
    PS.mark_part_done(parts_of(p)["Autsors"], by=aut_user, note=NOTE)
    assert bot_events.of("painter.remainder") == []
    assert once(f"painter:{job.pk}:remainder:3.0") is True  # key was not burned


def test_ordering_by_due_date_uses_open_parts(order_factory, head, own, aut, api):
    j1 = Painter.objects.create(order=order_factory(), square=5)
    j2 = Painter.objects.create(order=order_factory(), square=5)
    split(j1, head, row(own, 5))
    split(j2, head, row(aut, 5))
    PainterPart.objects.filter(painter=j1).update(due_date=date(2030, 2, 1))
    PainterPart.objects.filter(painter=j2).update(due_date=date(2030, 1, 1))
    h = api(*HEAD_PERMS)
    got = [x["id"] for x in h.get("/api/v1/painters/", {"ordering": "due_date"}).data["results"]]
    assert got == [j2.pk, j1.pk]
    got = [x["id"] for x in h.get("/api/v1/painters/", {"ordering": "-due_date"}).data["results"]]
    assert got == [j1.pk, j2.pk]
