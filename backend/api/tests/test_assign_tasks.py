"""After "Замер выполнен" the metering staff assign the design and/or price task to
one person each; only the chosen people get the task (Telegram/SMS)."""

from datetime import datetime

import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def commit(django_capture_on_commit_callbacks):
    """Run a request and then its on_commit callbacks (notifications go out on commit)."""

    def _run(fn, *args, **kwargs):
        with django_capture_on_commit_callbacks(execute=True):
            return fn(*args, **kwargs)

    return _run


@pytest.fixture
def notified(monkeypatch):
    sent, broadcast = [], []
    monkeypatch.setattr(
        "oauth.services.notify_user", lambda user, **kw: sent.append((user.pk, kw["url"]))
    )
    monkeypatch.setattr(
        "oauth.models.User.send_messages", classmethod(lambda cls, *a, **k: broadcast.append(a[0]))
    )
    return sent, broadcast


@pytest.fixture
def setup(api, make_staff, db_client):
    from metering.constants import MeteringStatus
    from metering.models import Metering

    metering = Metering.objects.create(client=db_client, date_time=datetime(2026, 10, 1, 10))
    Metering.objects.filter(pk=metering.pk).update(status=MeteringStatus.metering_done)
    metering.refresh_from_db()
    designer = make_staff("oauth.user_design", "design.view_design")
    pricer = make_staff("price.change_price", "price.view_price")
    zamerchi = api("metering.view_metering", "oauth.user_metering")
    return metering, designer, pricer, zamerchi


def test_assign_both_sends_task_to_both_only(setup, notified, commit):
    metering, designer, pricer, zamerchi = setup
    sent, broadcast = notified
    lists = zamerchi.get("/api/v1/meterings/assignees/").data
    assert designer.pk in [u["id"] for u in lists["designers"]]
    assert pricer.pk in [u["id"] for u in lists["pricers"]]
    assert designer.pk not in [u["id"] for u in lists["pricers"]]

    resp = commit(
        zamerchi.post,
        f"/api/v1/meterings/{metering.pk}/assign/",
        {"designer": designer.pk, "pricer": pricer.pk},
        format="json",
    )
    assert resp.status_code == 200, resp.data
    assert resp.data["design"]["user"]["id"] == designer.pk
    assert resp.data["price"]["user"]["id"] == pricer.pk
    assert sorted(pk for pk, _ in sent) == sorted([designer.pk, pricer.pk])
    assert broadcast == []  # nobody else got it


def test_assign_one_sends_to_that_one(setup, notified, commit):
    metering, designer, pricer, zamerchi = setup
    sent, broadcast = notified
    resp = commit(
        zamerchi.post,
        f"/api/v1/meterings/{metering.pk}/assign/",
        {"designer": designer.pk},
        format="json",
    )
    assert resp.status_code == 200
    assert resp.data["design"] is not None and resp.data["price"] is None
    assert sent == [(designer.pk, f"/designs/{resp.data['design']['id']}")]
    assert broadcast == []


def test_reassign_notifies_new_person(setup, notified, make_staff, commit):
    metering, designer, pricer, zamerchi = setup
    sent, _ = notified
    commit(
        zamerchi.post,
        f"/api/v1/meterings/{metering.pk}/assign/",
        {"designer": designer.pk},
        format="json",
    )
    other = make_staff("oauth.user_design", "design.view_design")
    commit(
        zamerchi.post,
        f"/api/v1/meterings/{metering.pk}/assign/",
        {"designer": other.pk},
        format="json",
    )
    assert [pk for pk, _ in sent] == [designer.pk, other.pk]


def test_assign_rules(setup, notified, api, commit):
    from metering.constants import MeteringStatus
    from metering.models import Metering

    metering, designer, pricer, zamerchi = setup
    url = f"/api/v1/meterings/{metering.pk}/assign/"
    assert commit(zamerchi.post, url, {}, format="json").status_code == 400  # nobody chosen
    assert (
        commit(zamerchi.post, url, {"designer": pricer.pk}, format="json").status_code == 400
    )  # no perm
    assert (
        api("metering.view_metering")
        .post(url, {"designer": designer.pk}, format="json")
        .status_code
        == 403
    )
    Metering.objects.filter(pk=metering.pk).update(status=MeteringStatus.created)
    assert commit(zamerchi.post, url, {"designer": designer.pk}, format="json").status_code == 400


def test_mine_filter_on_design_list(setup, notified, api, commit):
    metering, designer, pricer, zamerchi = setup
    commit(
        zamerchi.post,
        f"/api/v1/meterings/{metering.pk}/assign/",
        {"designer": designer.pk},
        format="json",
    )
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(designer)
    designer.user_permissions.add(
        *__import__(
            "django.contrib.auth.models", fromlist=["Permission"]
        ).Permission.objects.filter(content_type__app_label="design", codename="view_design")
    )
    assert client.get("/api/v1/designs/?mine=1").data["count"] == 1
    other = api("design.view_design")
    assert other.get("/api/v1/designs/?mine=1").data["count"] == 0
    assert other.get("/api/v1/designs/").data["count"] == 1


def test_refused_assign_creates_nothing_and_notifies_nobody(setup, notified, commit):
    from metering.design.models import Design
    from metering.price.models import Price

    metering, designer, pricer, zamerchi = setup
    Price.objects.create(metering=metering, user=pricer, done=True)
    sent, broadcast = notified
    sent.clear()
    resp = commit(
        zamerchi.post,
        f"/api/v1/meterings/{metering.pk}/assign/",
        {"designer": designer.pk, "pricer": pricer.pk},
        format="json",
    )
    assert resp.status_code == 400
    assert not Design.objects.filter(metering=metering).exists()
    assert sent == [] and broadcast == []


def test_candidates_must_be_able_to_open_the_task(setup, make_staff, api):
    metering, designer, pricer, zamerchi = setup
    blind = make_staff("oauth.user_design")  # no design.view_design
    ids = [u["id"] for u in zamerchi.get("/api/v1/meterings/assignees/").data["designers"]]
    assert designer.pk in ids and blind.pk not in ids


def test_same_assignee_again_reports_no_change(setup, notified, commit):
    metering, designer, pricer, zamerchi = setup
    url = f"/api/v1/meterings/{metering.pk}/assign/"
    first = commit(zamerchi.post, url, {"designer": designer.pk}, format="json")
    assert first.data["assigned"] == {"design": "created", "price": None}
    again = commit(zamerchi.post, url, {"designer": designer.pk}, format="json")
    assert again.data["assigned"] == {"design": None, "price": None}
