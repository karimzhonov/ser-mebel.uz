"""Rover two-step flow in depth: submit (worker) -> checking -> confirm (checker) -> done.
Service rules, on-commit side effects, REST API, detailing sync, bot endpoint, access
flag and the default lavozim migration."""

import importlib

import pytest
from django.apps import apps as global_apps
from django.contrib.auth.models import Group
from djmoney.money import Money

from core.exceptions import ServiceConflict, ServiceError, ServiceForbidden
from oauth import access as A
from order.rover import services as RS
from order.rover.models import Rover

pytestmark = pytest.mark.django_db

CHECKER = ("oauth.user_rover_checker", "rover.view_rover")
WORKER = ("rover.view_rover", "rover.change_rover")


def money(n="150000"):
    return Money(n, "UZS")


NOTE = "Fasad frezerlandi, 8 ta eshik"


def body(n="150000"):
    return {"price": {"amount": n, "currency": "UZS"}, "note": NOTE}


@pytest.fixture
def rover(order_factory):
    return Rover.objects.create(order=order_factory(), square=4, price=money("40000"))


@pytest.fixture
def worker(make_staff):
    return make_staff(*WORKER, name="Usta")


@pytest.fixture
def checker(make_staff):
    return make_staff(*CHECKER, name="Tekshiruvchi", telegram_id=111)


@pytest.fixture
def sent(monkeypatch, settings):
    """Bot envelopes queued with emit(); on_commit is NOT short-circuited here."""
    settings.TELEGRAM_BOT_TOKEN = "123456:TEST-BOT-TOKEN"
    out = []
    monkeypatch.setattr("core.tasks.notify_bot.delay", lambda env: out.append(env))
    return out


@pytest.fixture
def painting_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(RS, "notify_painting_ready", lambda order: calls.append(order.pk))
    _run_tasks_inline(monkeypatch)
    return calls


def _run_tasks_inline(monkeypatch):
    from order.rover import tasks

    monkeypatch.setattr(
        tasks.notify_painting_ready_task,
        "delay",
        lambda rid: tasks.notify_painting_ready_task.apply(args=(rid,)),
    )


def names(sent):
    return [e["event"] for e in sent]


# --- submit -----------------------------------------------------------------------


def test_submit_sets_fields(rover, worker):
    r = RS.submit_rover(rover, by=worker, price=money(), note=NOTE)
    r = Rover.objects.get(pk=r.pk)
    assert r.price == money()
    assert r.submitted_at is not None and r.submitted_by == worker
    assert r.done is False and r.state == "checking"
    assert r.checked_at is None and r.checked_by is None


@pytest.mark.parametrize("bad", ["0", "-5"])
def test_submit_rejects_non_positive_price(rover, worker, bad):
    with pytest.raises(ServiceError) as e:
        RS.submit_rover(rover, by=worker, price=money(bad), note=NOTE)
    assert e.value.field == "price"
    assert Rover.objects.get(pk=rover.pk).state == "new"


def test_submit_rejects_missing_price(rover, worker):
    with pytest.raises(ServiceError) as e:
        RS.submit_rover(rover, by=worker, price=None, note=NOTE)
    assert e.value.field == "price"


def test_submit_twice_and_after_done_conflict(rover, worker, checker):
    RS.submit_rover(rover, by=worker, price=money(), note=NOTE)
    with pytest.raises(ServiceConflict):
        RS.submit_rover(rover, by=worker, price=money("1"), note=NOTE)
    assert Rover.objects.get(pk=rover.pk).price == money()
    RS.confirm_rover(rover, by=checker)
    with pytest.raises(ServiceConflict):
        RS.submit_rover(rover, by=worker, price=money("1"), note=NOTE)


def test_submit_without_change_perm_forbidden(rover, checker):
    with pytest.raises(ServiceForbidden):
        RS.submit_rover(rover, by=checker, price=money(), note=NOTE)
    assert Rover.objects.get(pk=rover.pk).state == "new"


def test_submit_api_validation_and_403(rover, api):
    c = api(*WORKER)
    for payload in (
        {},
        {"price": {"amount": "0", "currency": "UZS"}, "note": NOTE},
        {"price": {"amount": "-3", "currency": "UZS"}, "note": NOTE},
    ):
        r = c.post(f"/api/v1/rovers/{rover.pk}/done/", payload, format="json")
        assert r.status_code == 400, (payload, r.data)
    r = api("rover.view_rover").post(f"/api/v1/rovers/{rover.pk}/done/", body(), format="json")
    assert r.status_code == 403
    r = c.post(f"/api/v1/rovers/{rover.pk}/done/", body(), format="json")
    assert r.status_code == 200 and r.data["state"] == "checking" and r.data["done"] is False
    r = c.post(f"/api/v1/rovers/{rover.pk}/done/", body(), format="json")
    assert r.status_code == 400  # the site API reports a conflict as 400 (409 is bot-only)


# --- rover.check event ------------------------------------------------------------


def test_check_event_after_commit_only_active_telegram_checkers(
    rover, worker, checker, make_staff, sent, django_capture_on_commit_callbacks
):
    make_staff(*CHECKER, name="Telegramsiz")  # checker without Telegram
    make_staff("oauth.user_rover_checker", name="Nofaol", telegram_id=222, is_active=False)
    make_staff(superuser=True, name="Super", telegram_id=333)  # no explicit permission row
    make_staff("rover.view_rover", name="Oddiy", telegram_id=444)  # not a checker
    with django_capture_on_commit_callbacks(execute=False) as cbs:
        RS.submit_rover(rover, by=worker, price=money(), note=NOTE)
    assert sent == []  # nothing before the commit
    for cb in cbs:
        cb()
    assert names(sent) == ["rover.check"]
    assert sent[0]["data"]["to"] == [111]
    assert sent[0]["data"]["rover"]["state"] == "checking"


def test_no_checkers_no_event(rover, worker, sent, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        r = RS.submit_rover(rover, by=worker, price=money(), note=NOTE)
    assert sent == [] and r.state == "checking"


# --- confirm ----------------------------------------------------------------------


def test_confirm_marks_done_notifies_once(
    rover, worker, checker, sent, painting_calls, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        RS.submit_rover(rover, by=worker, price=money(), note=NOTE)
    sent.clear()
    with django_capture_on_commit_callbacks(execute=False) as cbs:
        RS.confirm_rover(rover, by=checker)
    assert painting_calls == []  # deferred to commit
    for cb in cbs:
        cb()
    r = Rover.objects.get(pk=rover.pk)
    assert r.done and r.state == "done" and r.checked_by == checker and r.checked_at
    assert painting_calls == [rover.order_id]
    assert names(sent) == ["rover.checked"]


def test_second_confirm_conflict_no_side_effects(
    rover, worker, checker, sent, painting_calls, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        RS.submit_rover(rover, by=worker, price=money(), note=NOTE)
        RS.confirm_rover(rover, by=checker)
    sent.clear()
    painting_calls.clear()
    with django_capture_on_commit_callbacks(execute=True):
        with pytest.raises(ServiceConflict):
            RS.confirm_rover(rover, by=checker)
    assert sent == [] and painting_calls == []


def test_confirm_new_rover_is_error(rover, checker, painting_calls):
    with pytest.raises(ServiceError):
        RS.confirm_rover(rover, by=checker)
    assert not Rover.objects.get(pk=rover.pk).done and painting_calls == []


def test_confirm_requires_checker(rover, worker, painting_calls):
    RS.submit_rover(rover, by=worker, price=money(), note=NOTE)
    with pytest.raises(ServiceForbidden):
        RS.confirm_rover(rover, by=worker)
    assert not Rover.objects.get(pk=rover.pk).done


def test_confirm_api(rover, worker, api):
    RS.submit_rover(rover, by=worker, price=money(), note=NOTE)
    assert api(*WORKER).post(f"/api/v1/rovers/{rover.pk}/confirm/").status_code == 403
    c = api(*CHECKER)
    assert c.post(f"/api/v1/rovers/{rover.pk}/confirm/").status_code == 200
    assert c.post(f"/api/v1/rovers/{rover.pk}/confirm/").status_code == 400


# --- detailing sync ---------------------------------------------------------------


def _detailing(order):
    from order.detailing.models import Detailing

    return Detailing.objects.create(order=order, rover_square=2)


def test_detailing_square_recomputes_price_only_while_new(
    order_factory, admin_api, worker, checker
):
    order = order_factory()
    det = _detailing(order)
    rover = Rover.objects.get(order=order)
    assert rover.price == RS.auto_rover_price(2)

    def patch(sq):
        r = admin_api.patch(f"/api/v1/detailings/{det.pk}/", {"rover_square": sq}, format="json")
        assert r.status_code == 200, r.data
        return Rover.objects.get(pk=rover.pk)

    r = patch(5)
    assert r.square == 5 and r.price == RS.auto_rover_price(5)

    RS.submit_rover(r, by=worker, price=money("77777"), note=NOTE)
    r = patch(7)
    assert r.square == 7 and r.price == money("77777") and r.state == "checking"

    RS.confirm_rover(r, by=checker)
    r = patch(9)
    assert r.square == 9 and r.price == money("77777") and r.state == "done"


# --- list / filters / serializer --------------------------------------------------


def test_painter_list_hidden_while_checking(order_factory, worker, checker, admin_api):
    from order.painter.models import Painter

    order = order_factory()
    rover = Rover.objects.create(order=order, square=3)
    Painter.objects.create(order=order, square=5)
    assert admin_api.get("/api/v1/painters/").data["count"] == 0
    RS.submit_rover(rover, by=worker, price=money(), note=NOTE)
    assert admin_api.get("/api/v1/painters/").data["count"] == 0
    RS.confirm_rover(rover, by=checker)
    assert admin_api.get("/api/v1/painters/").data["count"] == 1


def test_serializer_actions_per_role_and_state(rover, worker, checker, api):
    w, c, both = api(*WORKER), api(*CHECKER), api(*WORKER, *CHECKER)
    url = f"/api/v1/rovers/{rover.pk}/"

    def acts(client):
        return client.get(url).data["actions"]

    assert acts(w) == {"done": True, "confirm": False, "due": False}
    assert acts(c) == {"done": False, "confirm": False, "due": False}
    assert acts(both) == {"done": True, "confirm": False, "due": False}
    RS.submit_rover(rover, by=worker, price=money(), note=NOTE)
    assert acts(w) == {"done": False, "confirm": False, "due": False}
    assert acts(c) == {"done": False, "confirm": True, "due": False}
    assert acts(both) == {"done": False, "confirm": True, "due": False}
    RS.confirm_rover(rover, by=checker)
    for client in (w, c, both):
        assert acts(client) == {"done": False, "confirm": False, "due": False}
    data = c.get(url).data
    assert data["state"] == "done" and data["state_label"] and data["checked_by_detail"]["name"]


def test_state_filter_and_stats(order_factory, worker, checker, admin_api):
    new = Rover.objects.create(order=order_factory(), square=1)
    chk = Rover.objects.create(order=order_factory(), square=1)
    done = Rover.objects.create(order=order_factory(), square=1)
    RS.submit_rover(chk, by=worker, price=money(), note=NOTE)
    RS.submit_rover(done, by=worker, price=money(), note=NOTE)
    RS.confirm_rover(done, by=checker)

    def ids(state):
        r = admin_api.get("/api/v1/rovers/", {"state": state})
        return {x["id"] for x in r.data["results"]}

    assert ids("new") == {new.pk}
    assert ids("checking") == {chk.pk}
    assert ids("done") == {done.pk}
    stats = admin_api.get("/api/v1/rovers/stats/").data
    assert stats["total"] == 3 and stats["done"] == 1 and stats["not_done"] == 1
    assert stats["checking"] == 1


def test_order_detail_production_rover_state(rover, worker, admin_api):
    url = f"/api/v1/orders/{rover.order_id}/"
    assert admin_api.get(url).data["production"]["rover"]["state"] == "new"
    RS.submit_rover(rover, by=worker, price=money(), note=NOTE)
    assert admin_api.get(url).data["production"]["rover"]["state"] == "checking"


# --- bot endpoint -----------------------------------------------------------------


def test_bot_confirm_statuses(rover, worker, checker, make_staff, bot_client, bot_events):
    make_staff("rover.view_rover", name="Oddiy", telegram_id=555)
    path = f"rovers/{rover.pk}/confirm/"
    assert bot_client.post("rovers/999999/confirm/", actor=111).status_code == 404
    assert bot_client.post(path, actor=777).status_code == 403  # not linked
    assert bot_client.post(path, actor=555).status_code == 403  # linked, no permission
    assert bot_client.post(path, actor=111).status_code == 400  # not handed in yet
    RS.submit_rover(rover, by=worker, price=money(), note=NOTE)
    ok = bot_client.post(path, actor=111)
    assert ok.status_code == 200 and ok.json()["rover"]["state"] == "done"
    assert bot_client.post(path, actor=111).status_code == 409
    assert len(bot_events.of("rover.checked")) == 1


# --- access flag + default lavozim -------------------------------------------------


def test_access_flag_rover_checker_round_trip():
    g = Group.objects.create(name="Test tekshiruvchi")
    out = A.set_group_access(g, {"flag_rover_checker": "view"})
    sec = {s["key"]: s for s in out["sections"]}["flag_rover_checker"]
    assert sec["is_flag"] and sec["level"] == "view"
    assert g.permissions.filter(codename="user_rover_checker").exists()
    again = {s["key"]: s["level"] for s in A.group_access(g)["sections"]}
    assert again["flag_rover_checker"] == "view"
    A.set_group_access(g, {"flag_rover_checker": "none"})
    assert not g.permissions.filter(codename="user_rover_checker").exists()


def _perms(g):
    return {
        f"{p.content_type.app_label}.{p.codename}"
        for p in g.permissions.select_related("content_type")
    }


def test_default_group_created_with_three_perms():
    mod = importlib.import_module("oauth.migrations.0016_rover_checker")
    Group.objects.filter(name="Rover tekshiruvchi").delete()
    mod.create_group(global_apps, None)
    g = Group.objects.get(name="Rover tekshiruvchi")
    assert _perms(g) == {"oauth.user_rover_checker", "rover.view_rover", "order.view_order"}
    mod.create_group(global_apps, None)  # idempotent
    assert Group.objects.filter(name="Rover tekshiruvchi").count() == 1


def test_existing_same_named_group_untouched():
    mod = importlib.import_module("oauth.migrations.0016_rover_checker")
    Group.objects.filter(name="Rover tekshiruvchi").delete()
    custom = Group.objects.create(name="rover  Tekshiruvchi")
    before = Group.objects.count()
    mod.create_group(global_apps, None)
    assert Group.objects.count() == before
    assert custom.permissions.count() == 0


def test_painting_ready_task_runs_once(rover, worker, checker, painting_calls):
    from order.rover.tasks import notify_painting_ready_task as task

    RS.submit_rover(rover, by=worker, price=money(), note=NOTE)
    RS.confirm_rover(rover, by=checker)  # no commit capture: on_commit is not run in tests
    assert task(rover.pk) is True
    assert task(rover.pk) is False  # redelivery is a no-op
    assert painting_calls == [rover.order_id]


def test_painting_ready_task_skips_unfinished_rover(rover, painting_calls):
    from order.rover.tasks import notify_painting_ready_task as task

    assert task(rover.pk) is False and painting_calls == []
