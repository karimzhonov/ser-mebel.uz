"""Write services for Painter (used by the REST API and the bot API).

Flow: the assembly manager picks a painter type (its `user` is the molyar) once the rover is
confirmed -> the job is *activated* (`started_at`, task card to the molyar, deadline
question to the production heads) -> the production head sets the deadline (auto after a
day) -> the molyar presses «Bajardim» with an izoh -> done. The price stays automatic
(type.price x square)."""

import logging
from datetime import timedelta

from constance import config
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from djmoney.money import Money

from accounting.text import now, today
from core.exceptions import ServiceConflict, ServiceError, ServiceForbidden
from oauth.constants import PRODUCTION_HEAD_PERMISSION

from . import events

logger = logging.getLogger(__name__)

NO_PERM = "Bu amal uchun huquq yetarli emas."
NOTE_MIN = 3
NOTE_MAX = 2000

# Painting starts only after milling: an order whose rover (if it has one) is not done
# yet is not the painter's work. Orders without a rover go to the painter directly.
ROVER_FINISHED = Q(order__rover__isnull=True) | Q(order__rover__done=True)


def ready_for_painter(queryset):
    """Painter rows the painter may work on now (rover finished or not needed)."""
    return queryset.filter(ROVER_FINISHED)


def waiting_for_rover(painter) -> bool:
    rover = getattr(painter.order, "rover", None)
    return rover is not None and not rover.done


def _ensure_rover_finished(painter):
    if waiting_for_rover(painter):
        raise ServiceError("Rover hali tugamagan — molyar ishi roverdan keyin boshlanadi")


def production_heads():
    from order.rover.services import production_heads as _heads

    return _heads()


def assembly_managers():
    from oauth.services import staff_with_permission
    from order.assembly.constants import ASSEMBLY_MANAGER_PERMISSION

    return staff_with_permission(ASSEMBLY_MANAGER_PERMISSION)


def _lock(pk):
    from .models import Painter

    return (
        Painter.objects.select_for_update(of=("self",))
        .select_related("order__client", "type__user", "done_by", "due_set_by")
        .get(pk=pk)
    )


def _type_user(painter):
    return painter.type.user if painter.type_id and painter.type.user_id else None


def _auto_price(painter) -> Money:
    t = painter.type
    return Money(amount=float(t.price.amount) * painter.square, currency=t.price.currency)


def _queue_task_sms(painter_id, user_id) -> None:
    from .tasks import painter_task_sms

    def _send():
        try:
            painter_task_sms.delay(painter_id, user_id)
        except Exception:
            logger.exception("Painter SMS not queued for painter %s", painter_id)

    transaction.on_commit(_send)


def _announce_task(painter) -> None:
    """The task card to the painter (Telegram) and an SMS when there is no Telegram."""
    user = _type_user(painter)
    if user is None:
        return
    events.painter_task(painter)
    _queue_task_sms(painter.pk, user.pk)


def _save(painter, *, by=None) -> None:
    painter._via_service = True
    if by is not None:
        painter._history_user = by
    painter.save()


def assign_painter_type(painter, painter_type, *, by=None):
    """The manager picks (or clears) the painter type. The first assignment after the rover
    is confirmed starts the job."""
    new_pk = getattr(painter_type, "pk", None)
    _ensure_rover_finished(painter)
    if painter_type is not None and painter_type.user_id is None:
        raise ServiceError("Bu turga molyar biriktirilmagan — avval molyarni tanlang")
    with transaction.atomic():
        locked = _lock(painter.pk)
        if locked.type_id == new_pk:
            return locked
        prev_user = _type_user(locked)
        locked.type = painter_type
        if painter_type is not None:
            locked.price = _auto_price(locked)
        locked.rev += 1
        first = False
        if not locked.done and painter_type is not None and locked.started_at is None:
            locked.started_at = timezone.now()
            first = True
        _save(locked, by=by)
        locked = _lock(locked.pk)
        if not locked.done:
            new_user = _type_user(locked)
            changed = (prev_user.pk if prev_user else None) != (new_user.pk if new_user else None)
            if prev_user is not None and changed:
                events.painter_unassigned(locked, prev=prev_user)
            if new_user is not None and changed:
                _announce_task(locked)
            if first:
                events.painter_due_ask(locked)
    return locked


def activate_painter(painter):
    """Start the job: the type (with a painter) is set, the rover is finished, nothing was
    started yet. Idempotent."""
    with transaction.atomic():
        locked = _lock(painter.pk)
        if (
            locked.done
            or _type_user(locked) is None
            or locked.started_at is not None
            or waiting_for_rover(locked)
        ):
            return locked
        locked.started_at = timezone.now()
        locked.rev += 1
        _save(locked)
        locked = _lock(locked.pk)
        _announce_task(locked)
        events.painter_due_ask(locked)
    return locked


def on_rover_finished(order) -> None:
    """The rover was confirmed: the managers hear painting can start; a job whose type
    was already picked starts now. A failed notification must not undo the rover."""
    from .models import Painter

    painter = Painter.objects.filter(order=order, done=False).first()
    if painter is None:
        return
    try:
        painter = Painter.objects.select_related("order__client", "type__user").get(pk=painter.pk)
        events.painter_ready(painter)
        activate_painter(painter)
    except Exception:
        logger.exception("Painter start failed for order %s", order.pk)


def legacy_type_saved(painter) -> None:
    """The frozen admin saved the type directly: recompute the price and start the job."""
    from .models import Painter

    if painter.type_id:
        price = _auto_price(painter)
        painter.price = price
        Painter.objects.filter(pk=painter.pk).update(
            price=price.amount, price_currency=str(price.currency)
        )
    try:
        activate_painter(painter)
    except Exception:
        logger.exception("Painter start failed for painter %s", painter.pk)


def mark_painter_done(painter, *, by, note):
    """The painter's «Bajardim»: an izoh (what was done) and the job is done at once."""
    note = note.strip() if isinstance(note, str) else ""
    with transaction.atomic():
        locked = _lock(painter.pk)
        # the row is checked as it is now, not as the caller's (maybe stale) instance
        is_assignee = locked.type_id is not None and locked.type.user_id == by.pk
        if not (is_assignee or by.has_perm("painter.change_painter")):
            raise ServiceForbidden(NO_PERM)
        if len(note) < NOTE_MIN:
            raise ServiceError("Izoh yozing: nima ish qilindi", field="note")
        if len(note) > NOTE_MAX:
            raise ServiceError(f"Izoh juda uzun (eng ko'pi {NOTE_MAX} belgi)", field="note")
        if locked.done:
            raise ServiceConflict("Molyar ishi allaqachon bajarilgan")
        _ensure_rover_finished(locked)
        locked.done = True
        locked.note = note
        locked.done_at = timezone.now()
        locked.done_by = by
        locked.rev += 1
        _save(locked, by=by)
        locked = _lock(locked.pk)
        events.painter_done(locked, by=by)
    return locked


def set_painter_due(painter, *, by, due_date=None, days=None):
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
        locked = _lock(painter.pk)
        if locked.done:
            raise ServiceConflict("Molyar ishi bajarilgan — muddatni o'zgartirib bo'lmaydi")
        if locked.due_date == due_date and not locked.due_auto:
            return locked
        how = "set" if locked.due_date is None else "moved"
        locked.due_date = due_date
        locked.due_auto = False
        locked.due_set_by = by
        locked.due_set_at = now()
        locked.rev += 1
        _save(locked, by=by)
        locked = _lock(locked.pk)
        events.painter_due_set(locked, how=how, by=by)
    return locked


def auto_set_painter_dues(at) -> int:
    """Nobody set a deadline within a day of the start: it becomes started + N days
    (PAINTER_AUTO_DUE_DAYS). Only jobs started 1-3 days ago are looked at."""
    from .models import Painter

    base = Painter.objects.filter(
        done=False,
        due_date__isnull=True,
        started_at__lte=at - timedelta(days=1),
        started_at__gte=at - timedelta(days=3),
    )
    days = int(config.PAINTER_AUTO_DUE_DAYS)
    count = 0
    for pk in list(base.order_by("pk").values_list("pk", flat=True)[:200]):
        with transaction.atomic():
            p = _lock(pk)
            if p.due_date is not None or p.done or p.started_at is None:
                continue
            p.due_date = p.started_at.date() + timedelta(days=days)
            p.due_auto = True
            p.due_set_by = None
            p.due_set_at = at
            p.rev += 1
            _save(p)
            p = _lock(pk)
            events.painter_due_set(p, how="auto", by=None)
            count += 1
    return count


def due_painter_reminders(at) -> dict:
    """Beat tick: auto deadlines first, then (from PAINTER_REMIND_HOUR) «1 day left» (the
    painter) and the daily overdue reminders (painter + heads) - each once."""
    from accounting.services import once

    from .models import Painter

    out = {"auto": auto_set_painter_dues(at), "soon": 0, "overdue": 0}
    if at.hour < int(config.PAINTER_REMIND_HOUR):
        return out
    d = at.date()
    base = ready_for_painter(
        Painter.objects.filter(done=False, due_date__isnull=False)
    ).select_related("order__client", "type__user", "due_set_by", "done_by")
    base = base.order_by("due_date", "pk")
    heads = events.tgs(production_heads())
    for p in base.filter(due_date=d + timedelta(days=1)):
        user = _type_user(p)
        # «1 day left» is for the painter only: don't burn its once-key without Telegram.
        if user is None or not user.telegram_id:
            continue
        if once(f"painter:{p.pk}:soon:{p.due_date.isoformat()}"):
            events.painter_remind(p, what="soon", heads=[])
            out["soon"] += 1
    for p in base.filter(due_date__lt=d):
        if once(f"painter:{p.pk}:od:{d.isoformat()}"):
            events.painter_remind(p, what="overdue", today=d, heads=heads)
            out["overdue"] += 1
    return out
