"""Admin-only deletion of staff accounts, HR employees and finance bot members."""

import pytest
from django.contrib.contenttypes.models import ContentType

from discussion.models import DiscussionMessage
from hr.models import Employee
from oauth.models import TelegramMember, TelegramRole, User


# ------------------------------------------------------------------ site users
def test_admin_deletes_user_without_history(admin_api, make_staff):
    victim = make_staff()
    r = admin_api.delete(f"/api/v1/users/{victim.pk}/")
    assert r.status_code == 204
    assert not User.objects.filter(pk=victim.pk).exists()


def test_non_admin_cannot_delete_user(api, make_staff):
    client = api("oauth.delete_user", "oauth.view_user")
    victim = make_staff()
    assert client.delete(f"/api/v1/users/{victim.pk}/").status_code == 403
    assert User.objects.filter(pk=victim.pk).exists()


def test_cannot_delete_yourself(admin_api):
    r = admin_api.delete(f"/api/v1/users/{admin_api.user.pk}/")
    assert r.status_code == 400
    assert User.objects.filter(pk=admin_api.user.pk).exists()


def test_user_with_history_is_kept(admin_api, make_staff):
    victim = make_staff()
    DiscussionMessage.objects.create(
        content_type=ContentType.objects.get_for_model(User),
        object_id=victim.pk,
        author=victim,
        message="salom",
    )
    r = admin_api.delete(f"/api/v1/users/{victim.pk}/")
    assert r.status_code == 400
    assert "Faol" in r.json()["detail"]
    assert User.objects.filter(pk=victim.pk).exists()


# ------------------------------------------------------------------ HR employees
@pytest.fixture
def employee(db):
    return Employee.objects.create(telegram_id=555001, number=1, name="Ali")


def test_admin_deletes_hr_employee(admin_api, employee):
    assert admin_api.delete(f"/api/v1/hr/employees/{employee.pk}/").status_code == 204
    assert not Employee.objects.filter(pk=employee.pk).exists()


def test_hr_manager_cannot_delete_employee(api, employee):
    client = api("hr.view_employee", "hr.change_employee", "hr.delete_employee")
    assert client.delete(f"/api/v1/hr/employees/{employee.pk}/").status_code == 403
    assert Employee.objects.filter(pk=employee.pk).exists()


# ------------------------------------------------------------------ finance members
@pytest.fixture
def blocked_member(db):
    return TelegramMember.objects.create(
        telegram_id=777001, name="Notanish", role=TelegramRole.BLOCKED
    )


def test_admin_deletes_blocked_member(admin_api, blocked_member):
    r = admin_api.delete(f"/api/v1/finance/members/{blocked_member.pk}/")
    assert r.status_code == 204
    assert not TelegramMember.objects.filter(pk=blocked_member.pk).exists()


def test_non_admin_cannot_delete_member(api, blocked_member):
    client = api("oauth.view_telegrammember", "oauth.delete_telegrammember")
    r = client.delete(f"/api/v1/finance/members/{blocked_member.pk}/")
    assert r.status_code == 403
    assert TelegramMember.objects.filter(pk=blocked_member.pk).exists()
