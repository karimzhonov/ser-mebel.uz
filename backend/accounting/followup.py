"""Order follow-up of the finance bot (siteNotify_ and friends in code.txt): deadline
reminders, the «Готов» payment sheet, bonus tracking, client feedback and «Saytga
kiritish» reminders.

The Apps Script scraped /admin/ every hour to see statuses; here the same checks read
order.Order directly and run from the scheduler (accounting/jobs.py). Nothing is sent
from here: each step emits an event (accounting/events.py) the bot service renders.
"""

from __future__ import annotations

import logging
from datetime import date

from constance import config
from django.db import transaction

from oauth.models import TelegramMember

from . import events as E
from . import services as S
from .models import ClientFeedback, OrderBonus, SiteEntryTask
from .text import days_between, today

log = logging.getLogger("finance.followup")


def receivers():
    return S.duty_members("is_bonus_receiver")


def deadline_people():
    return S.duty_members("is_deadline_receiver")


def is_receiver(m: TelegramMember) -> bool:
    return m.is_admin or m.is_bonus_receiver


# ------------------------------------------------------------------ bonus progress
def bonus_check(ref: str, ok_hour: bool):
    """bonusCheck_: rest reached 0 -> ask the receiver to close; after 30 days -> no
    bonus; day 2/6/29 -> «tomorrow the N-day term ends» reminders."""
    bn = OrderBonus.objects.filter(order_ref=str(ref), status="waiting").first()
    if not bn:
        return
    d = days_between(bn.ready_date, today())
    rest = None
    if bn.total > 0:
        ms = S.money_state(bn)
        rest = ms["rest"]
        if rest != bn.rest:
            bn.rest = rest
            bn.save(update_fields=["rest", "updated_at"])
        if rest <= S.bonus_tolerance(bn.currency):
            if not bn.zero_notified and ok_hour:
                bn.zero_notified = today()
                bn.save(update_fields=["zero_notified", "updated_at"])
                E.bonus_zero(bn, ms, d)
            return
    if d > 30:
        S.bonus_expire(bn, rest)
        return
    if not ok_hour or not bn.total:
        return
    for day, key, label, pct in [
        (2, "d3", "3 kunlik", "0.5"),
        (6, "d7", "7 kunlik", "0.4"),
        (29, "d30", "30 kunlik", "0.3"),
    ]:
        if d != day or bn.reminders.get(key):
            continue
        bn.reminders[key] = today().isoformat()
        bn.save(update_fields=["reminders", "updated_at"])
        E.bonus_term_reminder(bn, rest, label, pct)


# ------------------------------------------------------------------ feedback / site entry
def feedback_check(ok_hour: bool):
    """fikrCheck_: 3 days after Готов ask the feedback manager; remind after 2 more."""
    if not ok_hour:
        return
    t = today()
    for fb in ClientFeedback.objects.exclude(status="received"):
        if fb.status == "scheduled":
            if not fb.ready_date or days_between(fb.ready_date, t) < 3:
                continue
            fb.status, fb.asked_date = "asked", t
            fb.save(update_fields=["status", "asked_date"])
            E.feedback_ask(fb)
        elif (
            fb.status == "asked"
            and not fb.reminded
            and fb.asked_date
            and days_between(fb.asked_date, t) >= 2
        ):
            fb.reminded = t
            fb.save(update_fields=["reminded"])
            E.feedback_remind(fb)


def site_entry_remind(ok_hour: bool):
    if not ok_hour:
        return
    t = today()
    for task in SiteEntryTask.objects.filter(is_done=False, reminded__isnull=True):
        if days_between(task.date, t) < 1:
            continue
        task.reminded = t
        task.save(update_fields=["reminded"])
        E.site_entry_remind(task)


# ------------------------------------------------------------------ the hourly order pass
def bonus_since() -> date:
    """Only orders that became Готов after the bot moved here get a card (the Apps
    Script kept BONUS_BASE for the same reason). Set once, editable in settings."""
    raw = str(config.FIN_BONUS_SINCE or "").strip()
    try:
        return date.fromisoformat(raw)
    except ValueError:
        d = today()
        config.FIN_BONUS_SINCE = d.isoformat()
        return d


def deadline_reminders(infos):
    """Srok: 7 and 1 days left -> deadline people; 3 days left -> also the bonus
    receivers (the bot adds the address and a map link)."""
    t = today()
    for info in infos:
        if not info.end_date or info.bucket in ("yakun", "tugadi"):
            continue
        left = days_between(t, info.end_date)
        key = "7" if 3 < left <= 7 else "3" if 1 < left <= 3 else "1" if 0 <= left <= 1 else ""
        if not key or not S.once(f"srk:{info.ref}:{key}:{info.end_date.isoformat()}"):
            continue
        if key == "3":
            people = {m.pk: m for m in receivers() + deadline_people()}
            E.deadline(info, left, key, list(people.values()), E.WHO_DEADLINE_BONUS)
        else:
            E.deadline(info, left, key, deadline_people(), E.WHO_DEADLINE)


def _is_new_ready(info, since: date) -> bool:
    return bool(
        info.bucket in ("yakun", "tugadi") and info.ready_date and info.ready_date >= since
    )


def start_ready(info) -> bool:
    """A new «Готов» -> payment sheet to the bonus receiver, bonus tracking starts,
    warranty row and a feedback task are created. Once per order: OrderBonus.order_ref
    is unique, so the instant path and the hourly pass can't both send the card.
    Atomic: if a step fails the bonus row is rolled back and a later pass retries."""
    with transaction.atomic():
        bn, created = S.bonus_start(info, info.ready_date)
        if not created:
            return False
        E.ready_card(bn)
        S.warranty_ensure(info.ref, info.client, info.ready_date)
        S.feedback_schedule(info, info.ready_date)
        return True


def order_ready(ref: str) -> bool:
    """Right after an order became Готов (accounting/signals.py -> tasks.order_ready):
    the card goes at once, at any hour."""
    info = S.order_info(ref)
    if not info or not info.order or not _is_new_ready(info, bonus_since()):
        return False
    return start_ready(info)


def new_ready_orders(infos, ok_hour: bool):
    """Hourly fallback for Готов orders the instant path missed (worker down, status set
    with a queryset update, ...). At most 5 per pass, daytime only."""
    if not ok_hour:
        return
    since = bonus_since()
    sent = 0
    for info in infos:
        if not _is_new_ready(info, since):
            continue
        if OrderBonus.objects.filter(order_ref=info.ref).exists():
            continue
        if sent >= 5:
            break
        if start_ready(info):
            sent += 1


def hourly_orders(ok_hour: bool):
    infos = S.open_orders(["jarayonda", "yangi", "kutish", "yakun"])
    deadline_reminders(infos)
    new_ready_orders(infos, ok_hour)
    for bn in OrderBonus.objects.filter(status="waiting"):
        info = S.order_info(bn.order_ref)
        if (
            info
            and info.order
            and info.total
            and not bn.rest_base
            and (bn.total != info.total or bn.currency != info.currency)
        ):
            bn.total, bn.currency = info.total, info.currency
            bn.save(update_fields=["total", "currency", "updated_at"])
        try:
            bonus_check(bn.order_ref, ok_hour)
        except Exception:  # noqa: BLE001
            log.exception("bonus check %s", bn.order_ref)
    feedback_check(ok_hour)
    site_entry_remind(ok_hour)
