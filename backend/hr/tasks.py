"""Celery tasks of HR (davomat). Schedule: accounting/schedule.py."""

from celery import shared_task

from . import jobs


@shared_task
def tick():
    """Every minute: the davomat schedule (it keeps its own once-per-day markers)."""
    return jobs.tick()
