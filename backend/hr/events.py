"""HR (davomat) events for the Telegram bot (docs/BOT_CONTRACT.md, section 1.5).

Data only: ids, DTOs, no wording. `emit` queues after the DB transaction commits;
`send_*_sync` sends now and returns the bot's answer (the schedule needs to know whether
the person was reached before it counts an ask).
"""

from __future__ import annotations

import functools
import logging
from datetime import date

from core.bot_notify import deterministic_id, emit, send_event_sync

from . import services as S
from .models import Employee

log = logging.getLogger("hr.events")


def _safe(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:  # noqa: BLE001
            log.exception("event %s failed", fn.__name__)

    return wrapper


def admins() -> list[int]:
    return S.admin_ids()


def site_url() -> str:
    from django.conf import settings

    base = (getattr(settings, "ADMIN_BASE_URL", "") or "https://ser-mebel.uz").rstrip("/")
    return f"{base}/hr"


# ------------------------------------------------------------------ live (from handlers)
@_safe
def live_alert(kind: str, e: Employee, data: dict):
    """kind: late | late_comment | eta | excused. `late`, `late_comment` and `eta` go out
    only when MANAGER_LIVE_ALERTS is on (the caller checks); `excused` always."""
    emit(
        "hr.live_alert",
        {"admins": admins(), "kind": kind, "employee": S.employee_dto(e), "data": data},
    )


@_safe
def off_request(e: Employee, day: date):
    emit(
        "hr.off_request",
        {"admins": admins(), "employee": S.employee_dto(e), "day": day.isoformat()},
    )


@_safe
def off_request_answered(e: Employee, day: date, approve: bool):
    emit(
        "hr.off_request_answered",
        {"employee": S.employee_dto(e), "day": day.isoformat(), "approve": approve},
    )


@_safe
def employee_left(e: Employee):
    emit("hr.employee_left", {"admins": admins(), "name": e.name})


@_safe
def bot_added_to_group(title: str):
    emit("hr.bot_added_to_group", {"admins": admins(), "title": title})


# ------------------------------------------------------------------ admin commands / site
@_safe
def points_added(adj, from_site: bool):
    emit(
        "hr.points_added",
        {
            "employee": S.employee_dto(adj.employee),
            "value": adj.value,
            "reason": adj.reason,
            "from_site": from_site,
        },
    )


@_safe
def winner_announced(kind: str, period: str, result: dict):
    emit(
        "hr.winner_announced",
        {
            "kind": kind,
            "period": period,
            "employee": S.employee_dto(result["employee"]),
            "pts": result["pts"],
            "disc": result["disc"],
            "groups": result["groups"],
        },
    )


@_safe
def holiday_applied(hol_day: date, name: str, n: int, days: list[date]):
    emit(
        "hr.holiday_applied",
        {
            "hol_day": hol_day.isoformat(),
            "name": name,
            "n": n,
            "days": [d.isoformat() for d in days],
            "admins": admins(),
            "groups": [g.chat_id for g in S.groups()],
        },
    )


@_safe
def day_off_set(e: Employee, day: date):
    emit("hr.day_off_set", {"employee": S.employee_dto(e), "day": day.isoformat()})


@_safe
def leave_added(e: Employee, lv):
    emit(
        "hr.leave_added",
        {
            "employee": S.employee_dto(e),
            "date_from": lv.date_from.isoformat(),
            "date_to": lv.date_to.isoformat(),
            "reason": lv.reason,
        },
    )


@_safe
def hours_set(e: Employee):
    emit("hr.hours_set", {"employee": S.employee_dto(e)})


@_safe
def off_days_set(e: Employee):
    emit("hr.off_days_set", {"employee": S.employee_dto(e)})


# ------------------------------------------------------------------ schedule (hr/jobs.py)
@_safe
def morning(chat_id: int, starts: list[int]):
    emit(
        "hr.morning",
        {
            "chat_id": chat_id,
            "starts": [S.hm_str(x) for x in starts],
            "uniform_check": S.setting_bool("UNIFORM_CHECK"),
        },
    )


@_safe
def missing_list(chat_id: int, names: list[str]):
    emit("hr.missing_list", {"chat_id": chat_id, "names": names})


def _eid(day: date, name: str, e: Employee) -> str:
    return deterministic_id("hr", day.isoformat(), name, e.telegram_id)


def ask_eta(e: Employee, start_min: int, day: date, repeat: bool) -> dict:
    """SYNC. Raises core.bot_notify.BotUnavailable when the bot is down. The envelope id
    is fixed per (day, ask kind, person): a resend after a timeout is deduped by the bot."""
    return send_event_sync(
        "hr.ask_eta",
        {
            "employee": S.employee_dto(e),
            "start": S.hm_str(start_min),
            "day": day.isoformat(),
            "repeat": repeat,
        },
        envelope_id=_eid(day, "rep" if repeat else "ask", e),
    )


def out_reminder(e: Employee, day: date | None = None) -> dict:
    """SYNC."""
    return send_event_sync(
        "hr.out_reminder",
        {"employee": S.employee_dto(e)},
        envelope_id=_eid(day or S.now().date(), "outrem", e),
    )


def eta_passed(e: Employee, eta: str, day: date) -> dict:
    """SYNC."""
    return send_event_sync(
        "hr.eta_passed",
        {"employee": S.employee_dto(e), "eta": eta, "day": day.isoformat()},
        envelope_id=_eid(day, f"eta_{eta}", e),
    )


@_safe
def day_report(now_hm: str, report: dict):
    emit("hr.day_report", {"admins": admins(), "now_hm": now_hm, "report": report})


@_safe
def month_report(ym: str, report: dict):
    emit(
        "hr.month_report",
        {"admins": admins(), "ym": ym, "report": report, "site_url": site_url()},
    )


@_safe
def winner_pick(kind: str, period: str, rows: list[dict]):
    emit(
        "hr.winner_pick",
        {"admins": admins(), "kind": kind, "period": period, "rows": rows},
    )


@_safe
def holiday_ask(day: date, name: str):
    emit("hr.holiday_ask", {"admins": admins(), "day": day.isoformat(), "name": name})
