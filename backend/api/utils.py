import time
from datetime import date, timedelta

from constance import config
from django.db.models import Count, DateTimeField, F
from django.db.models.functions import TruncDate, TruncMonth
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from core.constants import DashboardFilterChoices


def int_param(params, name: str):
    """?name=<int> or None; anything else is a 400, not a 500."""
    value = params.get(name)
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValidationError({name: "Нотўғри қиймат."})


def date_param(params, name: str):
    value = params.get(name)
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValidationError({name: "Сана YYYY-MM-DD форматида бўлиши керак."})


_warning_days = {"value": None, "at": 0.0}


def warning_order_days() -> int:
    """config.WARNING_ORDER_DAYS, cached for 60s: constance's database backend has no
    cache here, and order_deadline runs once per row on every list."""
    now = time.monotonic()
    if _warning_days["value"] is None or now - _warning_days["at"] > 60:
        _warning_days["value"] = config.WARNING_ORDER_DAYS
        _warning_days["at"] = now
    return _warning_days["value"]


def today():
    # USE_TZ=False in this project, so now() is already local time.
    return timezone.now().date()


def apply_period(queryset, field: str, period: str | None):
    """?period=week|month|year — same windows as the admin "Дата" filter."""
    if period in DashboardFilterChoices.values:
        return queryset.filter(**DashboardFilterChoices.filters(period, field))
    return queryset


def csv_values(value: str | None) -> list[str]:
    return [v for v in (value or "").split(",") if v != ""]


def timeseries(queryset, field: str, period: str | None, value=None):
    """[{date, value}] grouped per day, or per month for the yearly view — the data
    behind the admin line charts."""
    if period == "year":
        bucket = TruncMonth(field)
    elif isinstance(queryset.model._meta.get_field(field), DateTimeField):
        bucket = TruncDate(field)
    else:  # already a plain date (e.g. Order.reception_date)
        bucket = F(field)
    rows = (
        queryset.order_by()
        .annotate(bucket=bucket)
        .values("bucket")
        .annotate(value=value or Count("pk"))
        .order_by("bucket")
    )
    return [
        {
            "date": row["bucket"].isoformat() if row["bucket"] else None,
            "value": float(row["value"] or 0),
        }
        for row in rows
    ]


def order_deadline(order) -> dict:
    """Days-left pill for an order — mirrors OrderAdmin.show_days / order_days_display.

    level: ok (done) | idle (no end date) | danger (overdue) | warn (within
    WARNING_ORDER_DAYS) | info (plenty of time).
    """
    from order.constants import OrderStatus

    if order.status == OrderStatus.DONE:
        return {"days": None, "level": "ok", "text": "Заказ готов"}
    if order.status == OrderStatus.WAITING or order.end_date is None:
        return {"days": None, "level": "idle", "text": "Ожидание даты сдачи"}
    days = (order.end_date - today()).days
    if days < 0:
        return {"days": days, "level": "danger", "text": f"Просрочен на {abs(days)} дн."}
    if days <= warning_order_days():
        return {"days": days, "level": "warn", "text": f"{days} дн. до сдачи"}
    return {"days": days, "level": "info", "text": f"{days} дн. до сдачи"}


def warning_filter(queryset, warning: str):
    """?warning=success|warning|danger — the admin "Дней осталось" filter, but on dates
    rather than on the Postgres-only `days` annotation."""
    from order.constants import OrderStatus

    t = today()
    qs = queryset.exclude(status=OrderStatus.DONE)
    if warning == "success":
        return qs.filter(end_date__gt=t + timedelta(days=warning_order_days()))
    if warning == "warning":
        return qs.filter(end_date__gte=t, end_date__lte=t + timedelta(days=warning_order_days()))
    if warning == "danger":
        return qs.filter(
            end_date__lt=t,
            status__in=[OrderStatus.DETAILING, OrderStatus.ASSEMBLY, OrderStatus.INSTALLING],
        )
    return queryset
