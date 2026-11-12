import pytest
from django.contrib.auth.models import Permission
from rest_framework.test import APIClient


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Telegram/SMS notifications must never leave the test process."""
    import requests

    def _blocked(*args, **kwargs):
        raise AssertionError("network call in test")

    monkeypatch.setattr(requests, "post", _blocked)
    monkeypatch.setattr("oauth.models.requests.post", _blocked)


@pytest.fixture(autouse=True)
def _tmp_media(settings, tmp_path):
    """Uploaded test files never land in the real MEDIA_ROOT."""
    settings.MEDIA_ROOT = str(tmp_path / "media")


@pytest.fixture(autouse=True)
def _no_offer_sms_queue(monkeypatch):
    """The Celery broker is not there in tests: the offer SMS is only queued."""
    monkeypatch.setattr("metering.tasks.offer_sms.delay", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _no_rover_sms_queue(monkeypatch):
    """No broker in tests: the new-rover SMS is only queued (call the task directly)."""
    monkeypatch.setattr("order.rover.tasks.rover_task_sms.delay", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _no_painter_sms_queue(monkeypatch):
    """No broker in tests: the new-painter-job SMS is only queued (call the task directly)."""
    monkeypatch.setattr("order.painter.tasks.painter_task_sms.delay", lambda *a, **k: None)
    monkeypatch.setattr("order.painter.tasks.painter_part_task_sms.delay", lambda *a, **k: None)


@pytest.fixture
def make_staff(db):
    from oauth.models import User

    counter = {"n": 0}

    def _make(*perms, superuser=False, **extra):
        counter["n"] += 1
        phone = f"+99890{counter['n']:07d}"
        if superuser:
            user = User.objects.create_superuser(phone=phone, password="pass12345", **extra)
        else:
            user = User.objects.create_user(
                phone=phone, password="pass12345", is_staff=True, **extra
            )
        for perm in perms:
            app_label, codename = perm.split(".")
            user.user_permissions.add(
                Permission.objects.get(content_type__app_label=app_label, codename=codename)
            )
        return User.objects.get(pk=user.pk)  # drop the permission cache

    return _make


@pytest.fixture
def default_measurer(make_staff):
    """The company's only measurer: create_metering preselects them. Opt in with
    `pytestmark = pytest.mark.usefixtures("default_measurer")` or as an argument."""
    return make_staff("oauth.user_metering", "metering.view_metering", name="Zamerchi")


@pytest.fixture
def default_manager(make_staff):
    """The company's only manager (metering.present_to_client): «Bajarildi» preselects
    them. Opt in with `pytestmark = pytest.mark.usefixtures("default_manager")` or as an
    argument."""
    return make_staff("metering.present_to_client", "metering.view_metering", name="Menejer")


@pytest.fixture
def api(make_staff):
    def _client(*perms, **kwargs):
        user = make_staff(*perms, **kwargs)
        client = APIClient()
        client.force_authenticate(user)
        client.user = user
        return client

    return _client


@pytest.fixture
def admin_api(api):
    return api(superuser=True)


# The internal bot channel: signed client + event collector, the finance fixtures (members,
# site_order) and the HR kit (clock, boss, group) its tests need.
from api.tests.botkit import (  # noqa: E402,F401
    bot_client,
    bot_events,
    contract,
    fake_replay_cache,
    members,
    site_order,
)
from hr.tests.hrkit import _fresh_settings_cache, boss, clock, group  # noqa: E402,F401
