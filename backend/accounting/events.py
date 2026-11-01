"""Finance events for the Telegram bot (docs/BOT_CONTRACT.md, section 1.5).

Each function builds the payload of one event (data only: ids, DTOs, no wording) and
queues it with `core.bot_notify.emit`, which sends after the DB transaction commits.
The bot service renders the messages. A failure here is logged and never raised:
a down bot must not undo a booking.
"""

from __future__ import annotations

import functools
import logging

from constance import config

from core.bot_notify import emit
from oauth.models import TelegramMember, User

from . import dto
from . import services as S
from .constants import CAT_ADVANCE, CAT_REST, OpKind

log = logging.getLogger("finance.events")

WHO_BONUS = "«Готов» bonus oluvchi"
WHO_SITE = "Saytga kirituvchi menejer"
WHO_FEEDBACK = "Mijoz fikri menejeri"
WHO_DEADLINE = "Srok xodimi"
WHO_DEADLINE_BONUS = "Srok va bonus xodimlari"
WHO_ACCOUNTANT = "Bugalter"


def _safe(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:  # noqa: BLE001
            log.exception("event %s failed", fn.__name__)

    return wrapper


def channel_id() -> str:
    return str(config.FIN_CHANNEL_ID or "").strip()


def admin_ids(exclude: TelegramMember | None = None) -> list[int]:
    return [a.telegram_id for a in S.admins() if not exclude or a.pk != exclude.pk]


def duty_target(duty: str, who: str) -> dict:
    """{to, fallback, fallback_who} for a duty event (the admins when nobody holds it)."""
    members, fallback = S.duty_recipients(duty)
    return {"to": [m.telegram_id for m in members], "fallback": fallback, "fallback_who": who}


# ------------------------------------------------------------------ operations
@_safe
def operation_created(op, author: TelegramMember | None = None, from_site: bool = False):
    """After a booking: channel post + the wallet owner when someone else booked it, and
    re-check the bonus when a client paid (saveTx_)."""
    emit(
        "finance.operation_created",
        {
            "operation": dto.operation_dto(op),
            "balance": dto.dec(S.balance(op.member)),
            "from_site": from_site,
            "notify_owner": author is None or author.pk != op.member_id,
            "owner_tg": op.member.telegram_id,
            "channel_id": channel_id(),
        },
    )
    if op.kind == OpKind.INCOME and op.order_ref and op.category.code in (CAT_ADVANCE, CAT_REST):
        from . import followup

        followup.bonus_check(op.order_ref, ok_hour=False)


@_safe
def operation_edited(op, before: dict, by_name: str):
    pair = S._pair_of(op)
    emit(
        "finance.operation_edited",
        {
            "operation": dto.operation_dto(op),
            "balance": dto.dec(S.balance(op.member)),
            "before": before,
            "by_name": by_name,
            "pair": (
                {
                    "operation": dto.operation_dto(pair),
                    "balance": dto.dec(S.balance(pair.member)),
                }
                if pair
                else None
            ),
            "channel_id": channel_id(),
        },
    )


@_safe
def operation_deleted(ops, by_name: str):
    emit(
        "finance.operation_deleted",
        {
            "operations": [dto.operation_dto(t) for t in ops],
            "by_name": by_name,
            "channel_id": channel_id(),
        },
    )


@_safe
def receipt_attached(op, file_id: str):
    emit(
        "finance.receipt_attached",
        {"operation": dto.operation_dto(op), "file_id": file_id, "channel_id": channel_id()},
    )


@_safe
def transfer_created(out, inc, by: TelegramMember | None):
    emit(
        "finance.transfer_created",
        {
            "out": dto.operation_dto(out),
            "inc": dto.operation_dto(inc),
            "inc_balance": dto.dec(S.balance(inc.member)),
            "inc_member": dto.member_dto(inc.member),
            "admins": admin_ids(exclude=by),
            "channel_id": channel_id(),
        },
    )


# ------------------------------------------------------------------ members
@_safe
def join_requested(m: TelegramMember):
    admins = admin_ids()
    supers = []
    if not admins:  # nobody is an admin yet: the site's superusers decide
        supers = list(
            User.objects.filter(
                is_superuser=True, is_active=True, telegram_id__isnull=False
            ).values_list("telegram_id", flat=True)
        )
    emit(
        "finance.join_requested",
        {"member": dto.member_dto(m), "admins": admins, "superusers": supers},
    )


@_safe
def member_approved(m: TelegramMember):
    emit("finance.member_approved", {"member": dto.member_dto(m)})


@_safe
def duty_assigned(m: TelegramMember, duty: str):
    emit("finance.duty_assigned", {"member": dto.member_dto(m), "duty": duty})


# ------------------------------------------------------------------ requests, month
@_safe
def request_created(req):
    emit("finance.request_created", {"request": dto.request_dto(req), "admins": admin_ids()})


@_safe
def request_answered(req, status: str, by_name: str, from_site: bool, op=None):
    bal = S.balance(req.member)
    emit(
        "finance.request_answered",
        {
            "request": dto.request_dto(req, bal),
            "status": status,
            "by_name": by_name,
            "from_site": from_site,
            "operation": dto.operation_dto(op) if op else None,
            "balance": dto.dec(bal),
            # an answer given on the site is not announced in the channel
            "post_to_channel": bool(status == "given" and op and not from_site),
            "channel_id": channel_id(),
        },
    )


@_safe
def month_submitted(member: TelegramMember, rep, summary: dict):
    emit(
        "finance.month_submitted",
        {
            "member": dto.member_dto(member),
            "month": rep.month,
            "summary": dto.month_summary_dto(summary),
            "note": rep.note,
            "closing": dto.dec(rep.balance),
            "admins": admin_ids(),
            "channel_id": channel_id(),
        },
    )


# ------------------------------------------------------------------ orders
@_safe
def manual_order_created(mo):
    emit(
        "finance.manual_order_created",
        {
            "order": dto.manual_order_dto(mo),
            "spent": dto.dec(S.order_stats(mo.ref)["spent"]),
            "channel_id": channel_id(),
        },
    )


@_safe
def manual_order_closed(mo):
    emit(
        "finance.manual_order_closed",
        {
            "order": dto.manual_order_dto(mo),
            "spent": dto.dec(S.order_stats(mo.ref)["spent"]),
            "channel_id": channel_id(),
        },
    )


# ------------------------------------------------------------------ money collected
@_safe
def handover_requested(op, who: str, ref: str, client: str, sum_text: str, rest_text: str):
    emit(
        "finance.handover_requested",
        {
            "operation": dto.operation_dto(op),
            "who": who,
            "ref": ref,
            "client": client,
            "sum_text": sum_text,
            "rest_text": rest_text,
            "admins": admin_ids(),
        },
    )


@_safe
def handover_resolved(op, action: str, client: str, sum_text: str):
    emit(
        "finance.handover_resolved",
        {
            "operation": dto.operation_dto(op),
            "action": action,
            "client": client,
            "sum_text": sum_text,
            "member_balance": dto.dec(S.balance(op.member)),
        },
    )


@_safe
def warranty_given(letter, by_name: str):
    emit(
        "finance.warranty_given",
        {"letter": dto.warranty_dto(letter), "by_name": by_name, "admins": admin_ids()},
    )


@_safe
def site_entry_created(task, collector_name: str):
    emit(
        "finance.site_entry_created",
        {"task": dto.task_dto(task), "collector_name": collector_name}
        | duty_target("is_site_entry", WHO_SITE),
    )


@_safe
def site_entry_done(task, by_name: str):
    emit(
        "finance.site_entry_done",
        {"task": dto.task_dto(task), "by_name": by_name, "admins": admin_ids()},
    )


@_safe
def feedback_received(fb, by_name: str, caption: str, file_id: str):
    emit(
        "finance.feedback_received",
        {
            "feedback": dto.feedback_dto(fb),
            "by_name": by_name,
            "caption": caption,
            "file_id": file_id,
            "admins": admin_ids(),
        },
    )


@_safe
def bonus_done(bn):
    """The order's money is fully collected: the bonus receivers (or the admins) are
    told; admins who are not receivers get it too."""
    receivers = S.duty_members("is_bonus_receiver")
    fallback = not receivers
    to = [m.telegram_id for m in (receivers or S.admins())]
    also = [] if fallback else [a for a in admin_ids() if a not in to]
    emit(
        "finance.bonus_done",
        {
            "bonus": dto.bonus_dto(bn),
            "to": to,
            "fallback": fallback,
            "fallback_who": WHO_BONUS,
            "also_admins": also,
        },
    )


# ------------------------------------------------------------------ follow-up (followup.py)
@_safe
def ready_card(bn):
    ms = S.money_state(bn)
    emit(
        "finance.ready_card",
        {
            "bonus": dto.bonus_dto(bn),
            "money_state": dto.money_state_dto(ms),
            "usd_rate": dto.dec(S.usd_rate(), 4),
        }
        | duty_target("is_bonus_receiver", WHO_BONUS),
    )


@_safe
def bonus_zero(bn, ms: dict, days: int):
    emit(
        "finance.bonus_zero",
        {
            "bonus": dto.bonus_dto(bn),
            "money_state": dto.money_state_dto(ms),
            "percent": dto.dec(S.bonus_percent(max(0, days))),
            "days": max(0, days),
        }
        | duty_target("is_bonus_receiver", WHO_BONUS),
    )


@_safe
def bonus_term_reminder(bn, rest, label: str, pct: str):
    emit(
        "finance.bonus_term_reminder",
        {"bonus": dto.bonus_dto(bn), "rest": dto.dec(rest), "label": label, "pct": pct}
        | duty_target("is_bonus_receiver", WHO_BONUS),
    )


@_safe
def feedback_ask(fb):
    emit(
        "finance.feedback_ask",
        {"feedback": dto.feedback_dto(fb)} | duty_target("is_feedback", WHO_FEEDBACK),
    )


@_safe
def feedback_remind(fb):
    emit(
        "finance.feedback_remind",
        {"feedback": dto.feedback_dto(fb)} | duty_target("is_feedback", WHO_FEEDBACK),
    )


@_safe
def site_entry_remind(task):
    emit(
        "finance.site_entry_remind",
        {"task": dto.task_dto(task)} | duty_target("is_site_entry", WHO_SITE),
    )


@_safe
def deadline(info, left_days: int, key: str, receivers: list[TelegramMember], who: str):
    """`receivers` are the people to tell; the admins when it is empty."""
    fallback = not receivers
    to = [m.telegram_id for m in (receivers or S.admins())]
    emit(
        "finance.deadline",
        {
            "order": {
                "ref": info.ref,
                "client": info.client,
                "end_date": dto.iso(info.end_date),
                "status_label": info.status_label,
                "phone": info.phone,
                "address": info.address,
            },
            "left_days": left_days,
            "key": key,
            "to": to,
            "fallback": fallback,
            "fallback_who": who,
        },
    )


@_safe
def salary_due(due: list):
    """«Ertaga oylik»: `due` = [(Worker, pay_date)] — to the accountant (the admins
    when nobody is marked «Bugalter»)."""
    emit(
        "finance.salary_due",
        {
            "workers": [
                {
                    "id": w.pk,
                    "name": w.name,
                    "group": w.group,
                    "position": w.position,
                    "pay_date": dto.iso(d),
                    "has_template": bool(w.salary_template_name),
                }
                for w, d in due
            ],
            **duty_target("is_accountant", WHO_ACCOUNTANT),
        },
    )


# ------------------------------------------------------------------ scheduled jobs (jobs.py)
@_safe
def daily_reminder(member: TelegramMember):
    emit(
        "finance.daily_reminder",
        {"member": dto.member_dto(member), "balance": dto.dec(S.balance(member))},
    )


@_safe
def month_end_reminder(member: TelegramMember, left_days: int):
    emit(
        "finance.month_end_reminder",
        {
            "member": dto.member_dto(member),
            "left_days": left_days,
            "balance": dto.dec(S.balance(member)),
        },
    )


@_safe
def month_late(member: TelegramMember, month: str):
    emit(
        "finance.month_late",
        {
            "member": dto.member_dto(member),
            "month": month,
            "balance": dto.dec(S.balance(member)),
        },
    )


@_safe
def month_late_admins(month: str, names: list[str]):
    emit("finance.month_late_admins", {"month": month, "names": names, "admins": admin_ids()})


@_safe
def admin_daily(day, summary: dict, rows, by_member: dict, silent: list[str], issues: list[dict]):
    emit(
        "finance.admin_daily",
        {
            "date": dto.iso(day),
            "summary": dto.day_summary_dto(summary),
            "ops_count": len(rows),
            "by_member": [{"name": k, "sum": dto.dec(v)} for k, v in by_member.items()],
            "silent": silent,
            "checks": {
                "count": len(issues),
                "high": sum(1 for i in issues if i["level"] == "h"),
            },
            "month": day.strftime("%Y-%m"),
            "admins": admin_ids(),
        },
    )


@_safe
def month_excel(month: str):
    emit("finance.month_excel", {"month": month, "admins": admin_ids()})
