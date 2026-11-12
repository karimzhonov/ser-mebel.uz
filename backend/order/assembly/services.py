"""Write services for Assembly (used by the REST API and the bot API).

Flow: detailing creates the row -> the order goes to «Сборка» (`Order.change_status` ->
`on_order_assembly`): the production heads are asked which assembler (team) gets the job ->
the job is *activated* (`started_at`, task card to the assembler, deadline question to the
heads) -> the head sets the deadline (auto after a day) -> «Yig'ildi» on the site
(`mark_assembly_done`, the order goes to «Установка») -> the assembler's «O'rnatildi» with
an izoh (`mark_installing_done` on the site / `finish_assembly` in the bot) sends the job to the
production head's check; the head's «Tayyor» (`confirm_assembly`) closes it and the order
becomes «Готов»."""

import logging
from datetime import timedelta

from constance import config
from django.db import models, transaction
from django.utils import timezone

from accounting.text import now, today
from core.exceptions import ServiceConflict, ServiceError, ServiceForbidden
from oauth.constants import ASSEMBLY_PERMISSION, PRODUCTION_HEAD_PERMISSION

from ..constants import OrderStatus
from . import events
from .constants import ASSEMBLY_MANAGER_PERMISSION

logger = logging.getLogger(__name__)

NO_PERM = "Bu amal uchun huquq yetarli emas."
NOTE_MIN = 3
NOTE_MAX = 2000

# Assembly work starts once detailing is finished: the order is in "Заказ на сырье"
# or later. Orders still waiting / created / in detailing are not assembly tasks yet.
NOT_YET_ASSEMBLY = [OrderStatus.WAITING, OrderStatus.CREATED, OrderStatus.DETAILING]
# the statuses in which an assembly job is live (reminders, bot finish)
IN_ASSEMBLY = (OrderStatus.ASSEMBLY, OrderStatus.INSTALLING)


def ready_for_assembly(queryset):
    """Assembly rows whose order has passed detailing."""
    return queryset.exclude(order__status__in=NOT_YET_ASSEMBLY)


def _ensure_past_detailing(assembly):
    if assembly.order.status in NOT_YET_ASSEMBLY:
        raise ServiceError("Detalirovka hali tugamagan — yig'ish undan keyin boshlanadi")


def in_assembly(assembly) -> bool:
    return assembly.order.status in IN_ASSEMBLY


def assemblers():
    """Users who may be picked as "Сборщик" (AssemblyForm's queryset)."""
    from oauth.models import User

    return User.objects.filter(
        models.Q(user_permissions__codename=ASSEMBLY_PERMISSION)
        | models.Q(groups__permissions__codename=ASSEMBLY_PERMISSION)
    ).distinct()


def active_assemblers():
    """Active staff who may be picked as the assembler (the team)."""
    from oauth.services import staff_with_permission

    return staff_with_permission(ASSEMBLY_PERMISSION)


def production_heads():
    from order.rover.services import production_heads as _heads

    return _heads()


def assembly_managers():
    from oauth.services import staff_with_permission

    return staff_with_permission(ASSEMBLY_MANAGER_PERMISSION)


def _lock(pk):
    from .models import Assembly

    return (
        Assembly.objects.select_for_update(of=("self",))
        .select_related("order__client", "user", "finished_by", "confirmed_by", "due_set_by")
        .get(pk=pk)
    )


def _save(assembly, *, by=None) -> None:
    if by is not None:
        assembly._history_user = by
    assembly.save()


def _queue_task_sms(assembly_id, user_id) -> None:
    from .tasks import assembly_task_sms

    def _send():
        try:
            assembly_task_sms.delay(assembly_id, user_id)
        except Exception:
            logger.exception("Assembly SMS not queued for assembly %s", assembly_id)

    transaction.on_commit(_send)


def _announce_task(assembly) -> None:
    """The task card to the assembler (Telegram) and an SMS when there is no Telegram."""
    if assembly.user_id is None:
        return
    events.assembly_task(assembly)
    _queue_task_sms(assembly.pk, assembly.user_id)


def assign_assembler(assembly, user, *, by=None, keep_started=False):
    """The production head picks (or clears) the assembler. The first pick while the order
    is in «Сборка» starts the job. `by=None` is the internal/legacy path (no permission
    check)."""
    if by is not None and not by.has_perm(f"oauth.{PRODUCTION_HEAD_PERMISSION}"):
        raise ServiceForbidden("Jamoani faqat Ishlab chiqarish rahbari tanlaydi")
    new_pk = getattr(user, "pk", None)
    if user is not None and not active_assemblers().filter(pk=new_pk).exists():
        raise ServiceError("Bu foydalanuvchi yig'uvchi emas", field="user")
    with transaction.atomic():
        locked = _lock(assembly.pk)
        _ensure_past_detailing(locked)
        if locked.finished_at is not None:
            raise ServiceConflict("O'rnatildi — yig'uvchini o'zgartirib bo'lmaydi")
        same = locked.user_id == new_pk
    if same:
        # re-picking the current assembler still starts a legacy row that never started
        return activate_assembly(assembly, by=by)
    with transaction.atomic():
        locked = _lock(assembly.pk)
        if locked.finished_at is not None:
            raise ServiceConflict("O'rnatildi — yig'uvchini o'zgartirib bo'lmaydi")
        if locked.user_id == new_pk:
            # a concurrent call set this assembler meanwhile: only make sure it started
            return activate_assembly(locked, by=by)
        if keep_started and locked.user_id and locked.started_at:
            # bot buttons may be stale or pressed by two heads at once: a started job
            # changes the assembler only on the site
            raise ServiceConflict(
                f"Jamoa allaqachon tanlangan: {locked.user.name} — o'zgartirish saytda"
            )
        prev = locked.user
        locked.user = user
        locked.rev += 1
        first = (
            not locked.installing_done
            and user is not None
            and locked.started_at is None
            and in_assembly(locked)
        )
        if first:
            locked.started_at = timezone.now()
        _save(locked, by=by)
        locked = _lock(locked.pk)
        if not locked.installing_done:
            if prev is not None:
                events.assembly_unassigned(locked, prev=prev)
            if user is not None and in_assembly(locked):
                _announce_task(locked)
            if first and locked.due_date is None:
                events.assembly_due_ask(locked)
    return locked


def activate_assembly(assembly, *, by=None):
    """Start the job: an assembler is picked, the order is in assembly, nothing was started
    yet. Idempotent."""
    with transaction.atomic():
        locked = _lock(assembly.pk)
        if (
            locked.installing_done
            or locked.user_id is None
            or locked.started_at is not None
            or not in_assembly(locked)
        ):
            return locked
        locked.started_at = timezone.now()
        locked.rev += 1
        _save(locked, by=by)
        locked = _lock(locked.pk)
        _announce_task(locked)
        if locked.due_date is None:
            events.assembly_due_ask(locked)
    return locked


def on_order_assembly(order) -> None:
    """The order moved to «Сборка»: the heads are asked to pick the team; a job whose
    assembler was already picked starts now. A failed notification must not undo the
    status change."""
    from accounting.services import once

    from .models import Assembly

    try:
        a = Assembly.objects.filter(order=order, installing_done=False).first()
        if a is None:
            return
        a = _lock_free(a.pk)
        if once(f"assembly:{a.pk}:ready"):
            events.assembly_ready(a)
        activate_assembly(a)
    except Exception:
        logger.exception("Assembly start failed for order %s", order.pk)


def _lock_free(pk):
    from .models import Assembly

    return Assembly.objects.select_related(
        "order__client", "user", "finished_by", "confirmed_by", "due_set_by"
    ).get(pk=pk)


def mark_assembly_done(assembly, *, by=None):
    """«Yig'ildi» (panel only): the order moves to "Установка". Only the assembler or a
    holder of `assembly.change_assembly` may press it (`by=None` = internal)."""
    if assembly.done:
        raise ServiceError("Yig'ish allaqachon bajarilgan")
    _ensure_past_detailing(assembly)
    with transaction.atomic():
        locked = _lock(assembly.pk)
        if by is not None and not (
            by.pk == locked.user_id or by.has_perm("assembly.change_assembly")
        ):
            raise ServiceForbidden(NO_PERM)
        if locked.done:
            raise ServiceError("Yig'ish allaqachon bajarilgan")
        _ensure_past_detailing(locked)
        locked.done = True
        locked.rev += 1
        _save(locked, by=by)
        order = locked.order
        order.status = OrderStatus.INSTALLING
        order.save(update_fields=["status"])
    return locked


def _finish(assembly, *, by, note, require_assembled):
    """The assembler's «O'rnatildi»: the job goes to the head's check. The order does NOT
    become «Tayyor» here - that is `confirm_assembly`."""
    note = note.strip() if isinstance(note, str) else ""
    with transaction.atomic():
        locked = _lock(assembly.pk)
        # the row is checked as it is now, not as the caller's (maybe stale) instance
        if not (locked.user_id == by.pk or by.has_perm("assembly.change_assembly")):
            raise ServiceForbidden(NO_PERM)
        if len(note) < NOTE_MIN:
            raise ServiceError("Izoh yozing: nima ish qilindi", field="note")
        if len(note) > NOTE_MAX:
            raise ServiceError(f"Izoh juda uzun (eng ko'pi {NOTE_MAX} belgi)", field="note")
        if locked.installing_done:
            raise ServiceConflict("Allaqachon tayyor")
        if locked.finished_at is not None:
            raise ServiceConflict("O'rnatildi, rahbar tasdiqlashi kutilmoqda")
        if require_assembled:
            if not locked.done:
                raise ServiceError("Avval yig'ishni bajaring")
        elif locked.order.status not in (*IN_ASSEMBLY, OrderStatus.DONE):
            raise ServiceError("Buyurtma hali yig'ishga yuborilmagan")
        locked.done = True
        locked.note = note
        locked.finished_at = timezone.now()
        locked.finished_by = by
        locked.rev += 1
        _save(locked, by=by)
        order = locked.order
        if order.status == OrderStatus.ASSEMBLY:
            order.status = OrderStatus.INSTALLING
            order._history_user = by
            order.save(update_fields=["status"])
        locked = _lock(locked.pk)
        events.assembly_done(locked, by=by)
    return locked


def confirm_assembly(assembly, *, by):
    """The production head's «Tayyor» after the assembler's «O'rnatildi»: the job is closed
    and the order becomes «Готов» (the accounting order_ready chain fires on commit, as
    the old `mark_installing_done` did)."""
    if not by.has_perm(f"oauth.{PRODUCTION_HEAD_PERMISSION}"):
        raise ServiceForbidden("Tasdiqlashni faqat Ishlab chiqarish rahbari qiladi")
    with transaction.atomic():
        locked = _lock(assembly.pk)
        if locked.installing_done:
            raise ServiceConflict("Allaqachon tayyor")
        if locked.finished_at is None:
            raise ServiceError("Yig'uvchi hali «O'rnatildi» bosmagan")
        locked.installing_done = True
        locked.done = True
        locked.confirmed_at = timezone.now()
        locked.confirmed_by = by
        locked.rev += 1
        _save(locked, by=by)
        order = locked.order
        if order.status != OrderStatus.DONE:
            order.status = OrderStatus.DONE
            order._history_user = by
            order.save(update_fields=["status"])
        locked = _lock(locked.pk)
        events.assembly_confirmed(locked, by=by)
    return locked


def mark_installing_done(assembly, *, by, note):
    """«O'rnatildi» on the site (after «Yig'ildi»): izoh, the job goes to the head's check."""
    return _finish(assembly, by=by, note=note, require_assembled=True)


def finish_assembly(assembly, *, by, note):
    """The assembler's «O'rnatildi» in the bot: one step (assembled + installed, waits for
    the head's «Tayyor»)."""
    return _finish(assembly, by=by, note=note, require_assembled=False)


def set_assembly_due(assembly, *, by, due_date=None, days=None):
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
        locked = _lock(assembly.pk)
        if locked.installing_done or locked.finished_at is not None:
            raise ServiceConflict("Yig'ish ishi bajarilgan — muddatni o'zgartirib bo'lmaydi")
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
        events.assembly_due_set(locked, how=how, by=by)
    return locked


def auto_set_assembly_dues(at) -> int:
    """Nobody set a deadline within a day of the start: it becomes started + N days
    (ASSEMBLY_AUTO_DUE_DAYS). Only jobs started 1-3 days ago are looked at."""
    from .models import Assembly

    base = Assembly.objects.filter(
        installing_done=False,
        finished_at__isnull=True,
        due_date__isnull=True,
        started_at__lte=at - timedelta(days=1),
        started_at__gte=at - timedelta(days=3),
    )
    days = int(config.ASSEMBLY_AUTO_DUE_DAYS)
    count = 0
    for pk in list(base.order_by("pk").values_list("pk", flat=True)[:200]):
        with transaction.atomic():
            a = _lock(pk)
            if (
                a.due_date is not None
                or a.installing_done
                or a.finished_at is not None
                or a.started_at is None
            ):
                continue
            a.due_date = a.started_at.date() + timedelta(days=days)
            a.due_auto = True
            a.due_set_by = None
            a.due_set_at = at
            a.rev += 1
            _save(a)
            a = _lock(pk)
            events.assembly_due_set(a, how="auto", by=None)
            count += 1
    return count


def due_assembly_reminders(at) -> dict:
    """Beat tick: auto deadlines first, then (from ASSEMBLY_REMIND_HOUR) «1 day left» (the
    assembler) and the daily overdue reminders (assembler + heads) - each once."""
    from accounting.services import once

    from .models import Assembly

    out = {"auto": auto_set_assembly_dues(at), "soon": 0, "overdue": 0}
    if at.hour < int(config.ASSEMBLY_REMIND_HOUR):
        return out
    d = at.date()
    base = (
        Assembly.objects.filter(
            installing_done=False,
            finished_at__isnull=True,
            due_date__isnull=False,
            order__status__in=IN_ASSEMBLY,
        )
        .select_related("order__client", "user", "due_set_by", "finished_by")
        .order_by("due_date", "pk")
    )
    heads = events.tgs(production_heads())
    for a in base.filter(due_date=d + timedelta(days=1)):
        # «1 day left» is for the assembler only: don't burn its once-key without Telegram.
        if a.user is None or not a.user.telegram_id:
            continue
        if once(f"assembly:{a.pk}:soon:{a.due_date.isoformat()}"):
            events.assembly_remind(a, what="soon", heads=[])
            out["soon"] += 1
    for a in base.filter(due_date__lt=d):
        if once(f"assembly:{a.pk}:od:{d.isoformat()}"):
            events.assembly_remind(a, what="overdue", today=d, heads=heads)
            out["overdue"] += 1
    return out
