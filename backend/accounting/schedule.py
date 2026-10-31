"""celery beat schedule of Moliya + HR, stored in the DB (django_celery_beat).

The hours come from constance (FIN_REMINDER_HOUR, FIN_ADMIN_REPORT_HOUR), so the
rows are re-synced after every migrate (accounting/apps.py) and whenever the
Moliya settings are saved (FinanceSettingsView). Edit hours in the settings, not
in the PeriodicTask rows — a sync overwrites them.
"""

from datetime import datetime

from constance import config
from django.conf import settings
from django_celery_beat.models import CrontabSchedule, PeriodicTask


def _hour(value, default: int) -> int:
    try:
        h = int(value)
    except (TypeError, ValueError):
        return default
    return h if 0 <= h <= 23 else default


def periodic_tasks() -> dict[str, tuple[str, dict]]:
    """name -> (task path, crontab fields)."""
    return {
        "moliya: kunlik eslatma": (
            "accounting.tasks.daily_reminder",
            {"minute": "0", "hour": str(_hour(config.FIN_REMINDER_HOUR, 19))},
        ),
        "moliya: rahbarga kunlik hisobot": (
            "accounting.tasks.admin_daily",
            {"minute": "0", "hour": str(_hour(config.FIN_ADMIN_REPORT_HOUR, 21))},
        ),
        "moliya: oy oxiri eslatmasi": ("accounting.tasks.month_job", {"minute": "0", "hour": "10"}),
        "moliya: buyurtmalar kuzatuvi": ("accounting.tasks.hourly_orders", {"minute": "0"}),
        "moliya: oylik eslatmasi": (
            "accounting.tasks.salary_reminder",
            {"minute": "0", "hour": "10"},
        ),
        "moliya: tozalash": ("accounting.tasks.cleanup", {"minute": "30", "hour": "3"}),
        "hr: davomat jadvali": ("hr.tasks.tick", {"minute": "*"}),
    }


def sync_periodic_tasks() -> None:
    wanted = periodic_tasks()
    for name, (task, fields) in wanted.items():
        cron = {
            "minute": "*",
            "hour": "*",
            "day_of_week": "*",
            "day_of_month": "*",
            "month_of_year": "*",
            **fields,
        }
        crontab, _ = CrontabSchedule.objects.get_or_create(timezone=settings.TIME_ZONE, **cron)
        pt, _ = PeriodicTask.objects.update_or_create(
            name=name,
            defaults={"task": task, "crontab": crontab, "interval": None, "enabled": True},
        )
        if pt.last_run_at is None:
            # With USE_TZ=False django-celery-beat reads naive last_run_at as UTC; left
            # empty it falls back to date_changed (local time, +5h) and the first run
            # slips by five hours.
            PeriodicTask.objects.filter(pk=pt.pk).update(last_run_at=datetime.utcnow())
    # tasks of this module that were renamed/removed
    for prefix in ("accounting.tasks.", "hr.tasks."):
        PeriodicTask.objects.filter(task__startswith=prefix).exclude(name__in=wanted).delete()
