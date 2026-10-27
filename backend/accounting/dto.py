"""Plain-dict DTOs of the finance data, as defined in docs/BOT_CONTRACT.md (section 1.2).

Used by the bot API (api/views/bot/finance.py) and by the event payload builders
(accounting/events.py). Decimals are strings, dates ISO, no Telegram wording.
"""

from __future__ import annotations

from decimal import Decimal

from constance import config

from . import services as S
from .constants import CAT_TRANSFER
from .models import (
    ClientFeedback,
    FinanceCar,
    FinanceCategory,
    ManualOrder,
    MoneyRequest,
    Operation,
    OrderBonus,
    SiteEntryTask,
    WarrantyLetter,
    Worker,
)
from .text import days_between, today


def dec(v, places: int = 2) -> str | None:
    if v is None:
        return None
    return str(S.D(v).quantize(Decimal(1).scaleb(-places)))


def iso(d) -> str | None:
    return d.isoformat() if d else None


def member_dto(m) -> dict | None:
    if m is None:
        return None
    user = m.user if m.user_id else None
    return {
        "id": m.pk,
        "telegram_id": m.telegram_id,
        "name": m.name,
        "username": m.username,
        "role": m.role,
        "is_admin": m.is_admin,
        "is_active_member": m.is_active_member,
        "is_task_only": m.is_task_only,
        "has_wallet": m.has_wallet,
        "is_site_entry": m.is_site_entry,
        "is_feedback": m.is_feedback,
        "is_bonus_receiver": m.is_bonus_receiver,
        "is_deadline_receiver": m.is_deadline_receiver,
        "site_user": (user.name or str(user.phone)) if user else None,
    }


def category_dto(c: FinanceCategory) -> dict:
    return {
        "code": c.code,
        "name": c.name,
        "emoji": c.emoji,
        "kind": c.kind,
        "admin_only": c.admin_only,
        "no_order": c.no_order,
        "archive": c.archive,
        "excluded": c.excluded,
    }


def operation_dto(op: Operation) -> dict:
    return {
        "number": op.number,
        "date": iso(op.date),
        "time": op.time.strftime("%H:%M") if op.time else None,
        "kind": op.kind,
        "amount": dec(op.amount),
        "currency": op.currency,
        "orig_amount": dec(op.orig_amount),
        "rate": dec(op.rate, 4),
        "category": category_dto(op.category),
        "member": {"telegram_id": op.member.telegram_id, "name": op.member.name},
        "author_tg": op.author.telegram_id if op.author_id else None,
        "order_ref": op.order_ref,
        "comment": op.comment,
        "worker": op.worker,
        "pay_type": op.pay_type,
        "receipt_file_id": op.receipt_file_id,
        "is_deleted": op.is_deleted,
        "handover": op.handover,
    }


def operation_row_dto(op: Operation, scope_all: bool) -> dict:
    """A list row: the Operation plus what the bot's list needs."""
    d = operation_dto(op)
    d["signed_amount"] = dec(op.signed_amount)
    d["internal"] = op.category.excluded if scope_all else op.category.code == CAT_TRANSFER
    return d


def order_brief_dto(info: S.OrderInfo) -> dict:
    return {
        "ref": info.ref,
        "client": info.client,
        "bucket": info.bucket,
        "ready_date": iso(info.ready_date),
    }


def order_card_dto(info: S.OrderInfo, stats: dict, full: bool) -> dict:
    """`full` (finance admins only) adds the contract money; for everyone else those
    keys are absent."""
    names = {c.code: c for c in FinanceCategory.objects.filter(code__in=list(stats["cats"]))}
    cats = []
    for code, v in sorted(stats["cats"].items(), key=lambda kv: -kv[1]):
        c = names.get(code)
        cats.append(
            {
                "code": code,
                "name": c.name if c else code,
                "emoji": c.emoji if c else "📦",
                "sum": dec(v),
            }
        )
    left = None
    if info.bucket == "yakun":
        left = max(
            0, int(config.FIN_READY_DAYS or 30) - days_between(info.ready_date or today(), today())
        )
    d = {
        "ref": info.ref,
        "client": info.client,
        "phone": info.phone,
        "bucket": info.bucket,
        "status_label": info.status_label,
        "ready_date": iso(info.ready_date),
        "end_date": iso(info.end_date),
        "ready_days_left": left,
        "manual": (
            {
                "is_closed": info.manual.is_closed,
                **({"price": dec(info.manual.price)} if full else {}),
            }
            if info.manual
            else None
        ),
        "stats": {
            "spent": dec(stats["spent"]),
            "collected": dec(stats["collected"]),
            "cats": cats,
            "last_ops": [operation_dto(t) for t in stats["rows"][-6:][::-1]],
        },
    }
    if full:
        d.update(
            total=dec(info.total),
            currency=info.currency,
            price_uzs=dec(info.price_uzs),
            paid=dec(info.paid),
            rest=dec(info.rest),
        )
    return d


def bonus_dto(bn: OrderBonus) -> dict:
    return {
        "order_ref": bn.order_ref,
        "client": bn.client,
        "description": bn.description,
        "total": dec(bn.total),
        "currency": bn.currency,
        "ready_date": iso(bn.ready_date),
        "status": bn.status,
        "rest": dec(bn.rest),
        "days": bn.days,
        "percent": dec(bn.percent),
        "bonus": dec(bn.bonus),
        "note": bn.note,
        "got_text": bn.got_text,
    }


def money_state_dto(ms: dict) -> dict:
    return {"paid": dec(ms["paid"]), "rest": dec(ms["rest"]), "src": ms["src"]}


def request_dto(req: MoneyRequest, balance=None) -> dict:
    return {
        "number": req.number,
        "member": member_dto(req.member),
        "amount": dec(req.amount),
        "currency": req.currency,
        "orig_amount": dec(req.orig_amount),
        "reason": req.reason,
        "status": req.status,
        "answer": req.answer,
        "created_at": req.created_at.strftime("%Y-%m-%dT%H:%M:%S"),
        "admin_messages": req.admin_messages or [],
        "member_balance": dec(S.balance(req.member) if balance is None else balance),
    }


def worker_dto(w: Worker) -> dict:
    return {"id": w.pk, "name": w.name, "group": w.group, "position": w.position}


def car_dto(c: FinanceCar) -> dict:
    return {"id": c.pk, "name": c.name}


def task_dto(t: SiteEntryTask) -> dict:
    return {
        "code": t.code,
        "order_ref": t.order_ref,
        "client": t.client,
        "sum_text": t.sum_text,
        "rest_text": t.rest_text,
        "taken_by": t.taken_by,
        "date": iso(t.date),
        "is_done": t.is_done,
    }


def feedback_dto(f: ClientFeedback) -> dict:
    return {
        "order_ref": f.order_ref,
        "client": f.client,
        "phone": f.phone,
        "status": f.status,
        "ready_date": iso(f.ready_date),
        "asked_date": iso(f.asked_date),
    }


def warranty_dto(w: WarrantyLetter) -> dict:
    return {"order_ref": w.order_ref, "client": w.client, "given": w.given}


def manual_order_dto(mo: ManualOrder) -> dict:
    return {
        "ref": mo.ref,
        "client": mo.client,
        "phone": mo.phone,
        "price": dec(mo.price),
        "is_closed": mo.is_closed,
    }


def month_summary_dto(sm: dict) -> dict:
    return {
        "month": sm["month"],
        "opening": dec(sm["opening"]),
        "income": dec(sm["income"]),
        "expense": dec(sm["expense"]),
        "closing": dec(sm["closing"]),
        "count": sm["count"],
    }


def day_summary_dto(sm: dict) -> dict:
    return {
        "expense": dec(sm["expense"]),
        "income": dec(sm["income"]),
        "balance": dec(sm["balance"]),
        "given_to_staff": dec(sm["given_to_staff"]),
        "boss_personal": dec(sm["boss_personal"]),
        "home": dec(sm["home"]),
        "transfers": dec(sm["transfers"]),
        "count": sm["count"],
    }
