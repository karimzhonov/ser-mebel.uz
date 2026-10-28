"""Celery app: background (.delay) and periodic (celery beat) tasks.

Worker: celery -A core worker -l info
Beat:   celery -A core beat -l info   (schedule lives in the DB, django_celery_beat)
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

app = Celery("core")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
