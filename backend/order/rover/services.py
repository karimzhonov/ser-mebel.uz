"""Write services for Rover (used by the REST API and the bot API).

State: new (submitted_at empty) -> the worker hands the job in with the actual amount
(checking) -> a checker confirms (done=True, the painter is notified). `done` keeps its
old meaning, so the painter / assembly / dashboard rules read it as before."""

import logging
from datetime import timedelta

from constance import config
from django.db import transaction
from django.utils import timezone
from djmoney.money import Money

from accounting.text import now, today
from core.exceptions import ServiceConflict, ServiceError, ServiceForbidden
from oauth.constants import PRODUCTION_HEAD_PERMISSION, ROVER_CHECKER_PERMISSION, ROVER_PERMISSION

from . import events
from .models import Rover, RoverState

logger = logging.getLogger(__name__)

NO_PERM = "Bu amal uchun huquq yetarli emas."


def auto_rover_price(square) -> Money:
    per = config.ROVER_PRICE_PER_SQUARE
    return Money(amount=float(per.amount) * float(square), currency=per.currency)


def sync_rover_from_detailing(order, square) -> Rover:
    """Detailing set the rover square: create the rover with the automatic price, or
    update the square (and the price, while the job is still `new`)."""
    with transaction.atomic():
        existing = Rover.objects.select_for_update().filter(order=order).first()
        if existing is None:
            return Rover.objects.create(order=order, square=square, price=auto_rover_price(square))
        existing.square = square
        fields = ["square"]
        if existing.state == RoverState.NEW:
            existing.price = auto_rover_price(square)
            fields.append("price")
        existing.save(update_fields=fields)
        return existing


def rover_checkers():
    from oauth.services import staff_with_permission

    return staff_with_permission(ROVER_CHECKER_PERMISSION)


def rover_workers():
    from oauth.services import staff_with_permission

    return staff_with_permission(ROVER_PERMISSION)


def production_heads():
    from oauth.services import staff_with_permission

    return staff_with_permission(PRODUCTION_HEAD_PERMISSION)


NOTE_MIN = 3
NOTE_MAX = 2000


def announce_new_rover(rover) -> None:
    """A new rover job: the full task card to the workers in the bot, the deadline
    question to the production heads, an SMS to workers without Telegram. Never raises -
    it runs inside the detailing save."""
    events.rover_task(rover)
    events.rover_due_ask(rover)
    rover_id = rover.pk
    try:
        from .tasks import rover_task_sms

        transaction.on_commit(lambda: _queue_task_sms(rover_task_sms, rover_id))
    except Exception:
        logger.exception("Rover SMS not queued for rover %s", rover_id)


def _queue_task_sms(task, rover_id) -> None:
    try:
        task.delay(rover_id)
    except Exception:
        logger.exception("Rover SMS not queued for rover %s", rover_id)


def submit_rover(rover, *, by, price, note) -> Rover:
    """The worker's «Bajarildi»: the actual amount and a note (what was done, how many
    doors) replace the price and the job waits for a checker."""
    if not by.has_perm("rover.change_rover"):
        raise ServiceForbidden(NO_PERM)
    if price is None or price.amount is None or price.amount <= 0:
        raise ServiceError("Summa 0 dan katta bo'lishi kerak", field="price")
    note = note.strip() if isinstance(note, str) else ""
    if len(note) < NOTE_MIN:
        raise ServiceError("Izoh yozing: nima ish qilindi, nechta eshik", field="note")
    if len(note) > NOTE_MAX:
        raise ServiceError(f"Izoh juda uzun (eng ko'pi {NOTE_MAX} belgi)", field="note")
    with transaction.atomic():
        locked = (
            Rover.objects.select_for_update(of=("self",))
            .select_related("order__client")
            .get(pk=rover.pk)
        )
        if locked.done:
            raise ServiceConflict("Rover allaqachon bajarilgan")
        if locked.submitted_at:
            raise ServiceConflict("Rover allaqachon tekshiruvga yuborilgan")
        locked.price = price
        locked.note = note
        locked.rev += 1
        locked.submitted_at = timezone.now()
        locked.submitted_by = by
        locked._history_user = by
        locked.save()
        events.rover_check(locked)
    return locked


def confirm_rover(rover, *, by) -> Rover:
    """The checker accepts the job: only now it is done and the painter hears of it."""
    if not by.has_perm(f"oauth.{ROVER_CHECKER_PERMISSION}"):
        raise ServiceForbidden(NO_PERM)
    with transaction.atomic():
        locked = (
            Rover.objects.select_for_update(of=("self",))
            .select_related("order__client")
            .get(pk=rover.pk)
        )
        if locked.done:
            raise ServiceConflict("Rover allaqachon tasdiqlangan")
        if locked.submitted_at is None:
            raise ServiceError("Rover hali tekshiruvga yuborilmagan")
        locked.done = True
        locked.rev += 1
        locked.checked_at = timezone.now()
        locked.checked_by = by
        locked._history_user = by
        locked.save()
        from .tasks import notify_painting_ready_task

        rover_id = locked.pk
        transaction.on_commit(lambda: notify_painting_ready_task.delay(rover_id))
        events.rover_checked(locked, by=by)
    return locked


def set_rover_due(rover, *, by, due_date=None, days=None) -> Rover:
    """The production head sets or moves the deadline: a date, or `days` from today."""
    if not by.has_perm(f"oauth.{PRODUCTION_HEAD_PERMISSION}"):
        raise ServiceForbidden(NO_PERM)
    if (due_date is None) == (days is None):
        raise ServiceError("Muddatni tanlang", field="due")
    t = today()
    if days is not None:
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 30:
            raise ServiceError("Muddat 1 dan 30 kungacha bo'lishi kerak", field="due")
        due_date = t + timedelta(days=days)
    if due_date < t:
        raise ServiceError("O'tgan sana — bugun yoki keyingi sanani tanlang", field="due")
    if due_date > t + timedelta(days=365):
        raise ServiceError("Muddat bir yildan uzoq bo'lishi mumkin emas", field="due")
    with transaction.atomic():
        locked = (
            Rover.objects.select_for_update(of=("self",))
            .select_related("order__client")
            .get(pk=rover.pk)
        )
        if locked.done:
            raise ServiceConflict("Rover bajarilgan — muddatni o'zgartirib bo'lmaydi")
        if locked.due_date == due_date and not locked.due_auto:
            return locked
        how = "set" if locked.due_date is None else "moved"
        locked.due_date = due_date
        locked.due_auto = False
        locked.due_set_by = by
        locked.due_set_at = now()
        locked.rev += 1
        locked._history_user = by
        locked.save()
        events.rover_due_set(locked, how=how, by=by)
    return locked


def auto_set_rover_dues(at) -> int:
    """Nobody set a deadline within a day of creation: it becomes created + N days
    (ROVER_AUTO_DUE_DAYS). Only jobs created 1-3 days ago are looked at."""
    base = Rover.objects.filter(
        done=False,
        submitted_at__isnull=True,
        due_date__isnull=True,
        created_at__lte=at - timedelta(days=1),
        created_at__gte=at - timedelta(days=3),
    )
    days = int(config.ROVER_AUTO_DUE_DAYS)
    count = 0
    for pk in list(base.order_by("pk").values_list("pk", flat=True)[:200]):
        with transaction.atomic():
            r = (
                Rover.objects.select_for_update(of=("self",))
                .select_related("order__client")
                .filter(pk=pk)
                .first()
            )
            if r is None or r.due_date is not None or r.done or r.submitted_at:
                continue
            r.due_date = r.created_at.date() + timedelta(days=days)
            r.due_auto = True
            r.due_set_by = None
            r.due_set_at = at
            r.rev += 1
            r.save()
            events.rover_due_set(r, how="auto", by=None)
            count += 1
    return count


def due_rover_reminders(at) -> dict:
    """Beat tick: auto deadlines first, then (from ROVER_REMIND_HOUR) «1 day left» and
    the daily overdue reminders - each once (accounting.services.once)."""
    from accounting.services import once

    out = {"auto": auto_set_rover_dues(at), "soon": 0, "overdue": 0}
    if at.hour < int(config.ROVER_REMIND_HOUR):
        return out
    d = at.date()
    base = (
        Rover.objects.filter(done=False, submitted_at__isnull=True, due_date__isnull=False)
        .select_related("order__client", "submitted_by", "checked_by", "due_set_by")
        .order_by("due_date", "pk")
    )
    # Recipients once per tick (not per rover); no cap, `once` keeps each send idempotent.
    workers = events.tgs(rover_workers())
    heads = events.tgs(production_heads())
    if not workers and not heads:
        return out
    # «1 day left» goes to workers only: don't burn its once-key while none has Telegram.
    for r in base.filter(due_date=d + timedelta(days=1)) if workers else ():
        if once(f"rover:{r.pk}:soon:{r.due_date.isoformat()}"):
            events.rover_remind(r, what="soon", workers=workers, heads=heads)
            out["soon"] += 1
    for r in base.filter(due_date__lt=d):
        if once(f"rover:{r.pk}:od:{d.isoformat()}"):
            events.rover_remind(r, what="overdue", today=d, workers=workers, heads=heads)
            out["overdue"] += 1
    return out


def notify_painting_ready(order):
    """Milling is finished: the painter side takes over (order.painter.services)."""
    from order.painter.services import on_rover_finished

    on_rover_finished(order)
