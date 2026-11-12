"""Write services for Painter (used by the REST API and the bot API).

A Molyar job (`Painter`, one per order) is split between teams by m²: one `PainterPart` per
team (`set_painter_parts`; the one-tap «whole job to team X» is `assign_whole_job`).
Flow: the production head picks the teams once the rover is confirmed -> every part is
*activated* (`started_at`, task card to the team's molyar, deadline question to the heads)
-> the head sets each part's deadline (auto after a day) -> each molyar presses «Bajardim»
with an izoh on their part. The job (`Painter.done`) is done only when the parts cover the
WHOLE square AND every part is done; an unassigned remainder keeps it open. Part price =
type.price x part square; the job price is the sum.

Lock order everywhere: the Painter row first (`_lock`), then its parts (`_lock_parts`)."""

import logging
import math
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from constance import config
from django.db import transaction
from django.db.models import Prefetch, Q
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


PART_ROVER_FINISHED = Q(painter__order__rover__isnull=True) | Q(painter__order__rover__done=True)


def ready_parts(queryset):
    """PainterPart rows whose job the painter may work on now."""
    return queryset.filter(PART_ROVER_FINISHED)


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
        .select_related("order__client", "done_by")
        .get(pk=pk)
    )


def _lock_parts(locked) -> list:
    """The job's parts, locked (call after `_lock`). Each part points at `locked`."""
    from .models import PainterPart

    parts = list(
        PainterPart.objects.select_for_update(of=("self",))
        .filter(painter=locked)
        .select_related("type__user", "done_by", "due_set_by")
        .order_by("pk")
    )
    for x in parts:
        x.painter = locked
    return parts


def _fresh(pk):
    """The job with its parts prefetched, for DTOs and the return value."""
    from .models import Painter, PainterPart

    return (
        Painter.objects.select_related("order__client", "done_by")
        .prefetch_related(
            Prefetch(
                "parts",
                queryset=PainterPart.objects.select_related(
                    "type__user", "done_by", "due_set_by"
                ).order_by("pk"),
            )
        )
        .get(pk=pk)
    )


def _part_price(ptype, square) -> Money:
    amount = Decimal(str(ptype.price.amount)) * Decimal(str(square))
    return Money(
        # like the field: whole currency units (decimal_places=0)
        amount=amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP),
        currency=ptype.price.currency,
    )


def _queue_part_sms(part_id, user_id) -> None:
    from .tasks import painter_part_task_sms

    def _send():
        try:
            painter_part_task_sms.delay(part_id, user_id)
        except Exception:
            logger.exception("Painter SMS not queued for part %s", part_id)

    transaction.on_commit(_send)


def can_override_part(user) -> bool:
    """May finish another team's part: only the full viewers (head / assembly manager /
    superuser) holding `painter.change_painter` - NOT every molyar, whose default group has
    that permission too."""
    from order.visibility import sees_full_order

    return bool(
        user.is_superuser or (user.has_perm("painter.change_painter") and sees_full_order(user))
    )


def _announce_part(part, reason="assigned") -> None:
    """The part's task card to its molyar (Telegram); an SMS when there is no Telegram."""
    user = part.user
    if user is None:
        return
    events.painter_part_task(part, reason=reason)
    if reason == "assigned":
        _queue_part_sms(part.pk, user.pk)


def _save(painter, *, by=None) -> None:
    painter._via_service = True
    if by is not None:
        painter._history_user = by
    painter.save()


def _save_part(part, *, by=None) -> None:
    if by is not None:
        part._history_user = by
    part.save()


def _remainder(painter, parts) -> float:
    return max(round(round(painter.square, 2) - round(sum(x.square for x in parts), 2), 2), 0.0)


def _combined_note(parts) -> str:
    done = [x for x in parts if x.done and x.note]
    if len(parts) == 1:
        return done[0].note if done else ""
    return "\n".join(f"{x.type.name}: {x.note}" for x in done)


def _sync_job(locked, parts, *, by=None) -> bool:
    """Recompute the job from its (locked, current) parts and save it. Returns True when the
    job just became done: every part done AND the parts cover the whole square. A job is
    never un-done."""
    priced = [x for x in parts if x.price is not None]
    if priced:
        locked.price = Money(
            amount=sum((Decimal(str(x.price.amount)) for x in priced), Decimal("0")),
            currency=priced[0].price.currency,
        )
    else:
        locked.price = None
    # deprecated column, kept in step so a rollback of the split stays safe
    locked.type = parts[0].type if len(parts) == 1 else None
    if locked.started_at is None:
        started = [x.started_at for x in parts if x.started_at]
        if started:
            locked.started_at = min(started)
    note = _combined_note(parts)
    if note or any(x.done for x in parts):
        locked.note = note
    became_done = bool(
        not locked.done and parts and all(x.done for x in parts) and not _remainder(locked, parts)
    )
    if became_done:
        locked.done = True
        locked.done_at = timezone.now()
        locked.done_by = by
    locked.rev += 1
    _save(locked, by=by)
    return became_done


def _clean_rows(rows) -> list[dict]:
    out = []
    for row in rows:
        square = row.get("square")
        if (
            isinstance(square, bool)
            or not isinstance(square, (int, float))
            or not math.isfinite(square)
            or round(square, 2) <= 0
        ):
            raise ServiceError("Maydon 0 dan katta bo'lishi kerak", field="parts")
        out.append({"id": row.get("id"), "type": row["type"], "square": round(float(square), 2)})
    return out


def set_painter_parts(painter, rows, *, by):
    """The production head splits the job between teams: `rows` = the desired OPEN parts
    `[{"id": part id | None, "type": PainterType, "square": m²}]` (done parts are never
    sent and stay as they are). An existing id keeps its start/deadline; a missing one is
    removed; a row without id is a new part. The sum may be below the job's square (the
    rest is given later) but never above."""
    if not by.has_perm(f"oauth.{PRODUCTION_HEAD_PERMISSION}"):
        raise ServiceForbidden("Jamoani faqat Ishlab chiqarish rahbari tanlaydi")
    return _apply_parts(painter, rows, by)


def _apply_parts(painter, rows, by):
    """The split write behind `set_painter_parts` (`by=None`: frozen-admin legacy path, no
    permission check)."""
    from .models import PainterPart

    _ensure_rover_finished(painter)
    rows = _clean_rows(rows)
    with transaction.atomic():
        locked = _lock(painter.pk)
        if locked.done:
            raise ServiceConflict("Molyar ishi bajarilgan")
        _ensure_rover_finished(locked)
        parts = _lock_parts(locked)
        open_by_id = {x.pk: x for x in parts if not x.done}
        done_parts = [x for x in parts if x.done]
        done_types = {x.type_id for x in done_parts}
        seen_ids, seen_types = set(), set()
        for row in rows:
            ptype = row["type"]
            rid = row["id"]
            if rid is not None:
                if rid in seen_ids:
                    raise ServiceError("Qism ikki marta berilgan", field="parts")
                seen_ids.add(rid)
                if rid not in open_by_id:
                    if any(x.pk == rid for x in done_parts):
                        raise ServiceConflict("Bajarilgan qismni o'zgartirib bo'lmaydi")
                    raise ServiceError("Qism topilmadi", field="parts")
            if ptype.user_id is None:
                raise ServiceError(
                    f"«{ptype.name}» jamoasiga molyar biriktirilmagan", field="parts"
                )
            if ptype.pk in seen_types or ptype.pk in done_types:
                raise ServiceError("Bir jamoa bitta ishda faqat bir marta", field="parts")
            seen_types.add(ptype.pk)
        # only what a save ADDS is checked: after detailing shrank the square an empty or
        # non-growing save still goes through (and can close the job)
        done_sum = round(sum(x.square for x in done_parts), 2)
        new_sum = round(sum(r["square"] for r in rows), 2)
        old_sum = round(sum(x.square for x in open_by_id.values()), 2)
        allowed = max(round(round(locked.square, 2) - done_sum, 2), 0.0)
        if new_sum > allowed and new_sum > old_sum:
            raise ServiceError(
                f"Jami {round(new_sum + done_sum, 2)} m² — umumiy maydondan "
                f"({round(locked.square, 2)} m²) katta",
                field="parts",
            )
        prices = [_part_price(r["type"], r["square"]) for r in rows]
        currencies = {str(m.currency) for m in prices} | {
            str(x.price.currency) for x in done_parts if x.price is not None
        }
        if len(currencies) > 1:
            raise ServiceError("Jamoalar narxi har xil valyutada", field="parts")
        by_id = {r["id"]: (r, m) for r, m in zip(rows, prices) if r["id"] is not None}

        # 1. removals (they free their team for the others)
        for pk, x in list(open_by_id.items()):
            if pk in by_id:
                continue
            if x.user is not None:
                # newer than any card the bot holds for this part, so its rev guard applies it
                x.rev += 1
                events.painter_part_unassigned(x, prev=x.user)
            x.delete()
            parts.remove(x)
        # 2. edits of existing parts; a team may move to the team another part just left
        pending = [(open_by_id[pk], r, m) for pk, (r, m) in by_id.items()]
        while pending:
            progress = False
            for item in list(pending):
                x, r, m = item
                ptype = r["type"]
                if ptype.pk != x.type_id and ptype.pk in {y.type_id for y in parts}:
                    continue
                pending.remove(item)
                progress = True
                _edit_part(x, r, m, by=by)
            if not progress:
                raise ServiceError(
                    "Ikki qism jamoasini almashtirib bo'lmaydi — avval biriga boshqa jamoa bering",
                    field="parts",
                )
        # 3. new parts
        now_ = timezone.now()
        for r, m in zip(rows, prices):
            if r["id"] is not None:
                continue
            x = PainterPart(
                painter=locked,
                type=r["type"],
                square=r["square"],
                price=m,
                started_at=now_,
                rev=1,
            )
            _save_part(x, by=by)
            parts.append(x)
            _announce_part(x)
            events.painter_part_due_ask(x)
        became_done = _sync_job(locked, parts, by=by)
        job = _fresh(locked.pk)
        events.painter_assigned(job)
        if became_done:
            events.painter_done(job, by=by)
    return job


def _edit_part(x, row, price, *, by) -> None:
    ptype = row["type"]
    prev_user = x.user
    type_changed = ptype.pk != x.type_id
    square_changed = row["square"] != x.square
    if not type_changed and not square_changed:
        return
    x.type = ptype
    x.square = row["square"]
    x.price = price
    x.rev += 1
    _save_part(x, by=by)
    new_user = x.user
    if type_changed:
        if (prev_user.pk if prev_user else None) != (new_user.pk if new_user else None):
            if prev_user is not None:
                events.painter_part_unassigned(x, prev=prev_user)
            _announce_part(x)
        elif square_changed:
            _announce_part(x, reason="resized")
    else:
        _announce_part(x, reason="resized")


def assign_whole_job(painter, painter_type, *, by=None, keep_started=False):
    """The one-tap «whole job to team X» (site `assign/`, bot buttons, frozen admin).
    `painter_type=None` clears the open parts. `by=None` is the frozen-admin legacy path
    (no permission check). An already split / started job is changed on the site only."""
    if by is None and painter_type is None:
        return painter
    if by is not None and not by.has_perm(f"oauth.{PRODUCTION_HEAD_PERMISSION}"):
        raise ServiceForbidden("Jamoani faqat Ishlab chiqarish rahbari tanlaydi")
    if painter_type is None:
        return _apply_parts(painter, [], by)
    _ensure_rover_finished(painter)
    if painter_type.user_id is None:
        raise ServiceError("Bu turga molyar biriktirilmagan — avval molyarni tanlang")
    with transaction.atomic():
        locked = _lock(painter.pk)
        if locked.done:
            raise ServiceConflict("Molyar ishi bajarilgan")
        parts = _lock_parts(locked)
        if not parts:
            row = {"id": None, "type": painter_type, "square": locked.square}
            return _apply_parts(locked, [row], by)
        if len(parts) == 1 and parts[0].type_id == painter_type.pk:
            return activate_parts(locked)
        only = parts[0] if len(parts) == 1 else None
        if only is not None and not only.done and not (keep_started and only.started_at):
            row = {"id": only.pk, "type": painter_type, "square": only.square}
            return _apply_parts(locked, [row], by)
        names = ", ".join(x.type.name for x in parts)
        raise ServiceConflict(f"Jamoa allaqachon tanlangan: {names} — o'zgartirish saytda")


assign_painter_type = assign_whole_job  # old name, kept for one release


def activate_parts(painter):
    """Start every open part that has a molyar and never started (rover finished).
    Idempotent."""
    with transaction.atomic():
        locked = _lock(painter.pk)
        if locked.done or waiting_for_rover(locked):
            return _fresh(locked.pk)
        parts = _lock_parts(locked)
        started = []
        for x in parts:
            if x.done or x.started_at is not None or x.user is None:
                continue
            x.started_at = timezone.now()
            x.rev += 1
            _save_part(x)
            started.append(x)
        if started:
            _sync_job(locked, parts)
            for x in started:
                _announce_part(x)
                if x.due_date is None:
                    events.painter_part_due_ask(x)
    return _fresh(painter.pk)


def on_rover_finished(order) -> None:
    """The rover was confirmed: the heads hear painting can start; parts whose team was
    already picked start now. A failed notification must not undo the rover."""
    from .models import Painter

    painter = Painter.objects.filter(order=order, done=False).first()
    if painter is None:
        return
    try:
        painter = _fresh(painter.pk)
        events.painter_ready(painter)
        if painter.type_id and not painter.parts.all():
            legacy_type_saved(painter)
        activate_parts(painter)
    except Exception:
        logger.exception("Painter start failed for order %s", order.pk)


def legacy_type_saved(painter) -> None:
    """The frozen admin saved the type directly: that is the whole job to this team (only
    for a job that is not split yet)."""
    from .models import Painter

    try:
        if painter.parts.exists():
            logger.info("Painter %s is split: the admin type edit is ignored", painter.pk)
            return
        assign_whole_job(Painter.objects.get(pk=painter.pk), painter.type, by=None)
    except Exception:
        logger.exception("Painter start failed for painter %s", painter.pk)


def mark_part_done(part, *, by, note):
    """A molyar's «Bajardim» on their part: an izoh (what was done). The job becomes done
    when this was the last open part AND the parts cover the whole square; if m² are still
    unassigned the heads are told (`painter.remainder`)."""
    from accounting.services import once

    note = note.strip() if isinstance(note, str) else ""
    with transaction.atomic():
        locked = _lock(part.painter_id)
        parts = _lock_parts(locked)
        cur = next((x for x in parts if x.pk == part.pk), None)
        if cur is None:
            raise ServiceConflict("Bu qism olib tashlangan")
        # checked as it is now, not as the caller's (maybe stale) instance
        is_assignee = cur.type.user_id == by.pk
        if not (is_assignee or can_override_part(by)):
            raise ServiceForbidden(NO_PERM)
        if len(note) < NOTE_MIN:
            raise ServiceError("Izoh yozing: nima ish qilindi", field="note")
        if len(note) > NOTE_MAX:
            raise ServiceError(f"Izoh juda uzun (eng ko'pi {NOTE_MAX} belgi)", field="note")
        if cur.done:
            raise ServiceConflict("Bu qism allaqachon bajarilgan")
        _ensure_rover_finished(locked)
        cur.done = True
        cur.note = note
        cur.done_at = timezone.now()
        cur.done_by = by
        cur.rev += 1
        _save_part(cur, by=by)
        became_done = _sync_job(locked, parts, by=by)
        job = _fresh(locked.pk)
        events.painter_part_done(cur, by=by, job_done=became_done)
        if became_done:
            events.painter_done(job, by=by)
        elif not locked.done and all(x.done for x in parts):
            left = _remainder(locked, parts)
            # no head with Telegram: keep the once-key unburnt for a later completion
            if (
                left
                and events.tgs(production_heads())
                and once(f"painter:{locked.pk}:remainder:{left}")
            ):
                events.painter_remainder(job, remainder=left)
    return job


def mark_painter_done(painter, *, by, note):
    """Job-level «Bajardim» (bot `painters/{id}/done/`, site `done/` without `part`): the
    actor's own open part - or, for a user with `painter.change_painter`, the only open
    part of the job."""
    parts = list(painter.parts.select_related("type__user"))
    open_parts = [x for x in parts if not x.done]
    own = [x for x in open_parts if x.type.user_id == by.pk]
    target = own or (open_parts if can_override_part(by) else [])
    if len(target) == 1:
        return mark_part_done(target[0], by=by, note=note)
    if len(target) > 1:
        raise ServiceConflict("Ish bo'lingan — o'z qismingizni tanlang (saytda)")
    involved = can_override_part(by) or any(x.type.user_id == by.pk for x in parts)
    if not involved:
        raise ServiceForbidden(NO_PERM)
    if type(painter).objects.filter(pk=painter.pk, done=True).exists():
        raise ServiceConflict("Molyar ishi allaqachon bajarilgan")
    raise ServiceConflict("Bajariladigan qism yo'q")


def _validate_due(due_date, days):
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
    return due_date


def set_part_due(part, *, by, due_date=None, days=None):
    """The production head sets or moves one part's deadline: a date, or `days` from today."""
    if not by.has_perm(f"oauth.{PRODUCTION_HEAD_PERMISSION}"):
        raise ServiceForbidden(NO_PERM)
    due_date = _validate_due(due_date, days)
    with transaction.atomic():
        locked = _lock(part.painter_id)
        parts = _lock_parts(locked)
        cur = next((x for x in parts if x.pk == part.pk), None)
        if cur is None:
            raise ServiceConflict("Bu qism olib tashlangan")
        if cur.done:
            raise ServiceConflict("Molyar ishi bajarilgan — muddatni o'zgartirib bo'lmaydi")
        if cur.due_date != due_date or cur.due_auto:
            how = "set" if cur.due_date is None else "moved"
            cur.due_date = due_date
            cur.due_auto = False
            cur.due_set_by = by
            cur.due_set_at = now()
            cur.rev += 1
            _save_part(cur, by=by)
            events.painter_part_due_set(cur, how=how, by=by)
    return _fresh(locked.pk)


def set_painter_due(painter, *, by, due_date=None, days=None):
    """Job-level deadline entry (bot `painters/{id}/due/`, site `due/` without `part`): it
    needs exactly one open part."""
    if not by.has_perm(f"oauth.{PRODUCTION_HEAD_PERMISSION}"):
        raise ServiceForbidden(NO_PERM)
    open_parts = list(painter.parts.filter(done=False).select_related("type__user"))
    if not open_parts:
        raise ServiceConflict("Molyar ishi bajarilgan — muddatni o'zgartirib bo'lmaydi")
    if len(open_parts) > 1:
        raise ServiceConflict("Ish bo'lingan — muddat har bir jamoa uchun alohida (saytda)")
    return set_part_due(open_parts[0], by=by, due_date=due_date, days=days)


def auto_set_painter_dues(at) -> int:
    """Nobody set a part's deadline within a day of its start: it becomes started + N days
    (PAINTER_AUTO_DUE_DAYS). Only parts started 1-3 days ago are looked at."""
    from .models import PainterPart

    base = PainterPart.objects.filter(
        done=False,
        due_date__isnull=True,
        started_at__lte=at - timedelta(days=1),
        started_at__gte=at - timedelta(days=3),
    )
    days = int(config.PAINTER_AUTO_DUE_DAYS)
    count = 0
    for pk, painter_id in list(base.order_by("pk").values_list("pk", "painter_id")[:200]):
        with transaction.atomic():
            locked = _lock(painter_id)
            x = next((y for y in _lock_parts(locked) if y.pk == pk), None)
            if x is None or x.due_date is not None or x.done or x.started_at is None:
                continue
            x.due_date = x.started_at.date() + timedelta(days=days)
            x.due_auto = True
            x.due_set_by = None
            x.due_set_at = at
            x.rev += 1
            _save_part(x)
            events.painter_part_due_set(x, how="auto", by=None)
            count += 1
    return count


def due_painter_reminders(at) -> dict:
    """Beat tick: auto deadlines first, then (from PAINTER_REMIND_HOUR) «1 day left» (the
    part's molyar) and the daily overdue reminders (molyar + heads) - each once per part."""
    from accounting.services import once

    from .models import PainterPart

    out = {"auto": auto_set_painter_dues(at), "soon": 0, "overdue": 0}
    if at.hour < int(config.PAINTER_REMIND_HOUR):
        return out
    d = at.date()
    base = ready_parts(PainterPart.objects.filter(done=False, due_date__isnull=False))
    base = base.select_related(
        "painter__order__client", "type__user", "due_set_by", "done_by"
    ).order_by("due_date", "pk")
    heads = events.tgs(production_heads())
    for x in base.filter(due_date=d + timedelta(days=1)):
        user = x.user
        # «1 day left» is for the molyar only: don't burn its once-key without Telegram.
        if user is None or not user.telegram_id:
            continue
        if once(f"painter_part:{x.pk}:soon:{x.due_date.isoformat()}"):
            events.painter_part_remind(x, what="soon", heads=[])
            out["soon"] += 1
    for x in base.filter(due_date__lt=d):
        if once(f"painter_part:{x.pk}:od:{d.isoformat()}"):
            events.painter_part_remind(x, what="overdue", today=d, heads=heads)
            out["overdue"] += 1
    return out
