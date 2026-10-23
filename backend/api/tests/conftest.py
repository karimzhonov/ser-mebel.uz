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
