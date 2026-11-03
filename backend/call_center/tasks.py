"""Celery tasks of the call-centre CRM. Schedule: accounting/schedule.py."""

from celery import shared_task

from accounting.text import now

from . import services


@shared_task
def task_reminders():
    """Every minute: remind the assignee of every task that came due (once per task)."""
    return services.due_task_reminders(now())
