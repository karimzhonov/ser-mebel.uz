import pytest
from django.test import Client
from django_celery_results.models import TaskResult

from hr.tasks import tick
from oauth.models import User


@pytest.mark.django_db
def test_task_result_is_saved_in_db():
    from core.celery import app

    assert app.conf.result_backend == "django-db"
    app.backend.store_result("t-1", [], "SUCCESS", request=None)
    assert TaskResult.objects.get(task_id="t-1").status == "SUCCESS"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url",
    [
        "/admin/django_celery_results/taskresult/",
        "/admin/django_celery_beat/periodictask/",
        "/admin/django_celery_beat/crontabschedule/",
    ],
)
def test_celery_admin_pages_open_for_superuser(url):
    TaskResult.objects.create(task_id="t-2", task_name="hr.tasks.tick", status="SUCCESS", result="[]")
    user = User.objects.create_superuser(phone="+998900000092", password="x")
    c = Client()
    c.force_login(user)
    assert c.get(url).status_code == 200


def test_tick_is_a_celery_task():
    assert tick.name == "hr.tasks.tick"
