"""Selectors for the Замеры kanban on the admin dashboard."""

from django.db.models import F, Q
from django.urls import reverse

from core.geo import UNSET
from core.kanban import DANGER, INFO, OK, PRIMARY, WARN, Column, build_board

from .constants import (
    METERING_MANAGE_PERMISSION,
    METERING_MAX_UPLOAD_MB,
    MeteringStatus,
)


def metering_board(to_card=None) -> list[dict]:
    """Columns for the "Замеры" kanban.

    Дизайн and Нарх are not statuses — they are the Design and Price rows hanging off
    a metering. A metering that has been measured therefore moves through three
    columns without its status changing: Замерга борилди while no design exists,
    Дизайн while the design is unfinished, Нарх once the design is done. Every
    measured metering matches exactly one of those three arms.
    """
    from .models import Metering

    changelist = reverse("admin:metering_metering_changelist")

    def by_status(status):
        return f"{changelist}?status={status}"

    measured = Q(status=MeteringStatus.metering_done)

    columns = [
        Column(
            "created",
            "Заявка олинди",
            "add",
            INFO,
            Q(status=MeteringStatus.created),
            more_url=by_status(MeteringStatus.created),
        ),
        Column(
            "other_day",
            "Бошқа кунга",
            "warning",
            WARN,
            Q(status=MeteringStatus.other_day),
            more_url=by_status(MeteringStatus.other_day),
        ),
        Column(
            "measured",
            "Замерга борилди",
            "straighten",
            INFO,
            measured & Q(design__isnull=True),
            more_url=by_status(MeteringStatus.metering_done),
            more_label="Все замеры →",
        ),
        # Дизайн and Нарх link to their own lists, which select a different set than
        # the column counts — so they get a label instead of an "Ещё N" the link
        # would not match.
        Column(
            "design",
            "Дизайн",
            "brush",
            PRIMARY,
            measured & Q(design__isnull=False, design__done=False),
            more_url=reverse("admin:design_design_changelist") + "?done=False",
            more_label="Все дизайны →",
        ),
        Column(
            "price",
            "Нарх чиқариш",
            "attach_money",
            PRIMARY,
            measured & Q(design__done=True),
            more_url=reverse("admin:price_price_changelist") + "?done=False",
            more_label="Все расчёты →",
        ),
        Column(
            "done",
            "Бажарилди",
            "check",
            OK,
            Q(status=MeteringStatus.done),
            more_url=by_status(MeteringStatus.done),
        ),
        Column(
            "sold_out",
            "Сотилди",
            "done_all",
            OK,
            Q(status=MeteringStatus.sold_out),
            collapsed=True,
            more_url=by_status(MeteringStatus.sold_out),
        ),
        Column(
            "dont_need",
            "Отмен болди",
            "close",
            DANGER,
            Q(status=MeteringStatus.dont_need),
            collapsed=True,
            more_url=by_status(MeteringStatus.dont_need),
        ),
    ]

    # date_time is nullable and Postgres sorts NULLs first on DESC — pin them last so
    # an undated metering can't head every column.
    queryset = Metering.objects.select_related("client", "design", "price").order_by(
        F("date_time").desc(nulls_last=True)
    )

    return build_board(queryset, columns, to_card or _metering_card)


def _metering_card(metering) -> dict:
    # Reverse OneToOne: both are select_related above, so this touches no extra query,
    # but the attribute still raises when the row is absent — hence getattr.
    design = getattr(metering, "design", None)
    price = getattr(metering, "price", None)

    return {
        "url": reverse("admin:metering_metering_change", args=[metering.pk]),
        "client": str(metering.client),
        "phone": str(metering.client.phone),
        "address": metering.address or "—",
        "desc": (metering.desc or "").strip(),
        "when": metering.date_time,
        "has_design": design is not None,
        "design_done": bool(design and design.done),
        "has_price": price is not None,
        "price_done": bool(price and price.done),
    }


# --- Write services (used by the REST API; mirror MeteringCreateForm / MeteringActions) ---


def metering_is_editable(metering) -> bool:
    """MeteringAdmin.has_change_permission: archived meterings are read-only."""
    return metering.status not in MeteringStatus.archive_statuses()


def create_metering(
    *,
    client,
    date_time,
    address=None,
    address_link=None,
    desc=None,
    invoice=None,
    author=None,
    lat=None,
    lon=None,
    measurer=None,
):
    """Mirrors MeteringCreateForm.save: linking an invoice marks it "Замерга борилади".

    The lead's location (point, pasted link, address) is inherited unless this call
    brings its own. The measurer is picked by the operator; with exactly one measurer
    in the company it is preselected. The measurer is told through the bot (or by SMS
    when Telegram is not linked)."""
    import logging

    from django.db import transaction

    from call_center.constants import SolutionChoice
    from core.exceptions import ServiceError
    from core.geo import make_point

    from . import events
    from .models import Metering

    if measurer is None:
        measurer = default_measurer()
    if measurer is None:
        if measurers().exists():
            raise ServiceError("Zamerchini tanlang", "measurer")
        # Nobody holds the permission yet (rollout): book it unassigned rather than
        # blocking the operator; any holder of user_metering can work it.
        logging.getLogger("metering").warning(
            "metering booked without a measurer: no active staff holds oauth.user_metering"
        )
    elif not measurers().filter(pk=measurer.pk).exists():
        raise ServiceError("Bu xodim zamerchi emas", "measurer")
    if invoice is not None and invoice.client_id != client.pk:
        raise ServiceError("Ariza boshqa mijozga tegishli")
    if lat is not None or lon is not None:
        point = make_point(lat, lon)
        if point is None:
            raise ServiceError("Lokatsiya koordinatalari noto'g'ri")
        lat, lon = point.lat, point.lon
    if invoice is not None:
        if lat is None and lon is None and not address_link:
            lat, lon, address_link = invoice.lat, invoice.lon, invoice.address_link
        if not (address or "").strip() and invoice.address:
            address = invoice.address

    with transaction.atomic():
        if invoice is not None:
            # lock order: Invoice -> Metering
            type(invoice).objects.select_for_update().get(pk=invoice.pk)
            old_metering = Metering.objects.select_for_update().filter(invoice=invoice).first()
            if old_metering is not None:
                from .constants import ClientResult

                refused = old_metering.client_result in (
                    ClientResult.design_declined,
                    ClientResult.price_declined,
                )
                if old_metering.status != MeteringStatus.dont_need and not refused:
                    raise ServiceError("Bu ariza uchun o'lchov allaqachon yaratilgan")
                # Metering.invoice is a OneToOne: a cancelled zamer (or one whose design /
                # price the client refused) lets go of the lead so the operator can book a
                # new one.
                old_metering.invoice = None
                old_metering._history_user = author
                old_metering.save(update_fields=["invoice"])
        now = _now()
        metering = Metering(
            client=client,
            date_time=date_time,
            address=address,
            address_link=address_link,
            lat=lat,
            lon=lon,
            desc=desc,
            invoice=invoice,
            measurer=measurer,
            created_by=author,
            scheduled_at=now,
        )
        metering._history_user = author
        metering.save()
        if invoice is not None:
            from call_center.services import log_solution

            from .price.services import attach_estimate

            attach_estimate(metering, invoice, by=author)

            old = invoice.solution
            invoice.solution = SolutionChoice.go_for_measured
            invoice.save()
            log_solution(invoice, old, int(SolutionChoice.go_for_measured), author)
        events.metering_assigned(metering, how="new")
        _queue_sms(metering)
    return metering


def set_metering_location(metering, *, point, link=UNSET, address=UNSET, by=None):
    """Attach / clear the metering's map location (and give a blank order the same).
    Returns (metering, changed, filled=[("order", id)]). Archived meterings are
    read-only."""
    from django.db import transaction

    from core.exceptions import ServiceError
    from core.geo import copy_location, resolve_location

    with transaction.atomic():
        locked = _lock(metering)
        if not metering_is_editable(locked):
            raise ServiceError("Bajarilgan o'lchovni tahrirlab bo'lmaydi")
        new_lat, new_lon, new_link = resolve_location(locked, point, link)
        fields = []
        if (locked.lat, locked.lon, locked.address_link) != (new_lat, new_lon, new_link):
            locked.lat, locked.lon, locked.address_link = new_lat, new_lon, new_link
            fields += ["lat", "lon", "address_link"]
        if address is not UNSET:
            text = (address or "").strip()
            # an empty address clears it, but only while a point still locates the job
            if (text or locked.lat is not None) and text != (locked.address or ""):
                locked.address = text
                fields.append("address")
        if fields:
            locked._history_user = by  # not the request's user: it may be the bot principal
            locked.save(update_fields=fields)
        filled = []
        if locked.lat is not None or locked.address_link:
            from order.models import Order

            order = Order.objects.select_for_update().filter(metering=locked).first()
            if order is not None:
                order_fields = copy_location(locked, order)
                if order_fields:
                    order._history_user = by
                    order.save(update_fields=order_fields)
                    filled.append(("order", order.pk))
    for name in ("lat", "lon", "address", "address_link"):
        setattr(metering, name, getattr(locked, name))
    return metering, bool(fields), filled


# --- Zamer stage 1: people, permissions ---------------------------------------------

OPEN_STATUSES = [MeteringStatus.created, MeteringStatus.other_day]
CANCELLABLE_STATUSES = [*OPEN_STATUSES, MeteringStatus.metering_done]
MIN_REASON = 3
_PRESETS = ("1h", "tomorrow", "2d")


def _now():
    # USE_TZ=False, TIME_ZONE=Asia/Tashkent: naive local time
    from datetime import datetime

    return datetime.now()


def _explicit_holders(app_label, codename):
    """Active staff holding app_label.codename EXPLICITLY (own or via a group).
    Deliberately not users_with_perm: that adds every superuser."""
    from django.db.models import Q

    from oauth.models import User

    perm = Q(
        user_permissions__codename=codename,
        user_permissions__content_type__app_label=app_label,
    ) | Q(
        groups__permissions__codename=codename,
        groups__permissions__content_type__app_label=app_label,
    )
    return (
        User.objects.filter(is_active=True, is_staff=True)
        .filter(perm)
        .distinct()
        .order_by("name", "phone")
    )


def measurers():
    """Who can be sent to measure: active staff holding oauth.user_metering EXPLICITLY
    (own or via a group). Deliberately not users_with_perm: that adds every superuser."""
    from oauth.constants import METERING_PERMISSION

    return _explicit_holders("oauth", METERING_PERMISSION)


def default_measurer():
    """The measurer when there is exactly one (preselected), else None."""
    found = list(measurers()[:2])
    return found[0] if len(found) == 1 else None


def can_work_metering(user, metering) -> bool:
    """May act as the measurer of this metering (measured / finish / upload)."""
    from oauth.constants import METERING_PERMISSION

    if user is None:
        return False
    if user.is_superuser or user.has_perm(f"metering.{METERING_MANAGE_PERMISSION}"):
        return True
    if metering.measurer_id is not None:
        return metering.measurer_id == user.pk
    return user.has_perm(f"oauth.{METERING_PERMISSION}")


def can_reschedule_or_cancel(user, metering) -> bool:
    return can_work_metering(user, metering) or bool(
        user is not None and user.has_perm("metering.change_metering")
    )


def metering_operator(metering):
    """The operator who sold the zamer: the lead's owner, else whoever created it."""
    if metering.invoice_id is not None:
        return metering.invoice.assigned_to
    return metering.created_by


def _bump(metering, locked, fields):
    """Copy the changed fields of the locked row back onto the caller's instance."""
    for name in fields:
        setattr(metering, name, getattr(locked, name))
    return metering


def _lock(metering):
    """Row locks in the one global order Invoice -> Metering -> Design -> Price ->
    InvoiceTask: the lead's row first (when there is one), then the metering (the offer
    rows follow in _lock_offer)."""
    from call_center.models import Invoice

    from .models import Metering

    if metering.invoice_id is not None:
        Invoice.objects.select_for_update(of=("self",)).get(pk=metering.invoice_id)
    return Metering.objects.select_for_update(of=("self",)).get(pk=metering.pk)


def _need_status(locked, allowed, *, already=None):
    from core.exceptions import ServiceConflict
    from core.i18n import metering_status as label

    if locked.status in allowed:
        return
    if already is not None and locked.status in already:
        raise ServiceConflict("Allaqachon belgilangan")
    if locked.status in MeteringStatus.archive_statuses():
        raise ServiceConflict("Bu zamer yopilgan")
    raise ServiceConflict(f"«{label(locked.status)}» holatida bu amalni bajarib bo'lmaydi")


def _tg_ids(*users):
    return [u.telegram_id for u in users if u is not None and u.is_active and u.telegram_id]


def _queue_sms(metering):
    """SMS only for a measurer without Telegram; after commit, via Celery."""
    from django.db import transaction

    measurer = metering.measurer
    if measurer is None or measurer.telegram_id:
        return
    mid, rev = metering.pk, metering.rev

    def _go():
        try:
            from .tasks import assignment_sms

            assignment_sms.delay(mid, rev)
        except Exception:  # noqa: BLE001 - a broken broker must not undo the booking
            import logging

            logging.getLogger("metering").exception("could not queue the zamer SMS")

    transaction.on_commit(_go)


# --- Zamer stage 1: writes ------------------------------------------------------------


def set_metering_measurer(metering, *, measurer, by):
    """Hand the zamer to another measurer (boss / whoever may change meterings)."""
    from django.db import transaction

    from core.exceptions import ServiceError, ServiceForbidden

    from . import events

    if not (
        by.is_superuser
        or by.has_perm(f"metering.{METERING_MANAGE_PERMISSION}")
        or by.has_perm("metering.change_metering")
    ):
        raise ServiceForbidden("Zamerchini almashtirish huquqi yo'q")
    if not measurers().filter(pk=measurer.pk).exists():
        raise ServiceError("Bu xodim zamerchi emas", "measurer")
    with transaction.atomic():
        locked = _lock(metering)
        _need_status(locked, [*OPEN_STATUSES, MeteringStatus.metering_done])
        if locked.measurer_id == measurer.pk:
            return _bump(metering, locked, ["measurer", "rev", "scheduled_at"])
        old = locked.measurer
        locked.measurer = measurer
        locked.scheduled_at = _now()
        locked.rev += 1
        locked._history_user = by
        locked.save(update_fields=["measurer", "scheduled_at", "rev"])
        _bump(metering, locked, ["measurer", "rev", "scheduled_at"])
        if old is not None:
            events.metering_changed(
                locked, how="reassigned", by=by, to_users=[old], to_name=_name(measurer)
            )
        events.metering_assigned(locked, how="reassigned")
        _queue_sms(locked)
    return metering


def _name(user):
    return (user.name or str(user.phone)) if user is not None else None


def mark_metering_measured(metering, *, by):
    """«O'lchov oldim»: the measurer took the measurements (files + next step follow on
    the site). Status -> metering_done."""
    from django.db import transaction

    from call_center.services import log_metering
    from core.exceptions import ServiceForbidden

    from . import events

    with transaction.atomic():
        locked = _lock(metering)
        if not can_work_metering(by, locked):
            raise ServiceForbidden("Bu zamer sizga biriktirilmagan")
        _need_status(
            locked,
            OPEN_STATUSES,
            already=[MeteringStatus.metering_done, MeteringStatus.done],
        )
        locked.status = MeteringStatus.metering_done
        locked.measured_at = _now()
        locked.rev += 1
        locked._history_user = by
        locked.save(update_fields=["status", "measured_at", "rev"])
        _bump(metering, locked, ["status", "measured_at", "rev"])
        if locked.invoice_id is not None:
            log_metering(
                locked.invoice,
                author=by,
                event="measured",
                meta={"metering_id": locked.pk},
            )
        events.metering_changed(locked, how="measured", by=by, to_users=[locked.measurer])
    return metering


def _round_up_half_hour(moment):
    from datetime import timedelta

    floor = moment.replace(second=0, microsecond=0)
    if floor < moment:
        floor += timedelta(minutes=1)
    return floor + timedelta(minutes=(-floor.minute) % 30)


def _reschedule_target(locked, now, date_time, preset, text):
    from datetime import datetime, time, timedelta

    from call_center.services import parse_due
    from core.exceptions import ServiceError

    clock = (
        locked.date_time.time().replace(second=0, microsecond=0) if locked.date_time else time(10)
    )
    if date_time is not None:
        target = date_time.replace(second=0, microsecond=0)
    elif preset is not None:
        if preset == "1h":
            target = _round_up_half_hour(now + timedelta(hours=1))
        elif preset == "tomorrow":
            target = datetime.combine((now + timedelta(days=1)).date(), clock)
        elif preset == "2d":
            target = datetime.combine((now + timedelta(days=2)).date(), clock)
        else:
            raise ServiceError("Noma'lum vaqt tanlovi", "time")
    else:
        try:
            target = parse_due(text, now, default_time=clock)
        except ServiceError as e:
            raise ServiceError(e.message, "time")
    if target <= now:
        raise ServiceError("O'tgan vaqt — kelajakdagi vaqtni kiriting", "time")
    return target


def reschedule_metering(metering, *, by, date_time=None, preset=None, text=None):
    """Move the zamer to another time (the measurer agrees it with the client; no SMS to
    the client). Exactly one of date_time / preset ("1h" | "tomorrow" | "2d") / text."""
    from django.db import transaction

    from call_center.dto import dt
    from call_center.services import log_metering
    from core.exceptions import ServiceError, ServiceForbidden

    from . import events

    given = [x for x in (date_time, preset, (text or "").strip() or None) if x is not None]
    if len(given) != 1:
        raise ServiceError("Yangi vaqtni kiriting", "time")
    with transaction.atomic():
        locked = _lock(metering)
        if not can_reschedule_or_cancel(by, locked):
            raise ServiceForbidden("Bu zamerni ko'chirish huquqi yo'q")
        _need_status(locked, OPEN_STATUSES)
        now = _now()
        old = locked.date_time
        target = _reschedule_target(locked, now, date_time, preset, (text or "").strip() or None)
        locked.status = MeteringStatus.other_day
        locked.date_time = target
        locked.scheduled_at = now
        locked.rev += 1
        locked._history_user = by
        locked.save(update_fields=["status", "date_time", "scheduled_at", "rev"])
        _bump(metering, locked, ["status", "date_time", "scheduled_at", "rev"])
        operator = metering_operator(locked)
        if locked.invoice_id is not None:
            log_metering(
                locked.invoice,
                author=by,
                event="rescheduled",
                meta={"metering_id": locked.pk, "from": dt(old), "to": dt(target)},
            )
        watchers = [operator] if operator is not None and operator.pk != by.pk else []
        events.metering_changed(
            locked,
            how="rescheduled",
            by=by,
            to_users=[locked.measurer],
            watchers=watchers,
        )
    return metering


def cancel_metering(metering, *, by, reason):
    """«Bekor bo'ldi»: the zamer will not happen. The lead goes back to its operator as a
    call task. Returns (metering, lead_returned)."""
    from django.db import transaction

    from call_center.services import return_lead_from_metering
    from core.exceptions import ServiceConflict, ServiceError, ServiceForbidden

    from . import events

    reason = (reason or "").strip()
    if len(reason) < MIN_REASON:
        raise ServiceError("Sababini yozing", "reason")
    returned = False
    with transaction.atomic():
        locked = _lock(metering)  # Invoice -> Metering -> tasks
        if not can_reschedule_or_cancel(by, locked):
            raise ServiceForbidden("Bu zamerni bekor qilish huquqi yo'q")
        if locked.status == MeteringStatus.dont_need:
            raise ServiceConflict("Allaqachon bekor qilingan")
        _need_status(locked, CANCELLABLE_STATUSES)
        locked.status = MeteringStatus.dont_need
        locked.cancel_reason = reason
        locked.cancelled_at = _now()
        locked.rev += 1
        locked._history_user = by
        locked.save(update_fields=["status", "cancel_reason", "cancelled_at", "rev"])
        _bump(metering, locked, ["status", "cancel_reason", "cancelled_at", "rev"])
        if locked.invoice_id is not None:
            returned = return_lead_from_metering(
                locked.invoice,
                by=by,
                reason=reason,
                metering_id=locked.pk,
                booked_by=locked.created_by,
                measurer=locked.measurer,
            )
        events.metering_changed(locked, how="cancelled", by=by, to_users=[locked.measurer])
    return metering, returned


def folder_tree_ids(roots) -> list[int]:
    """The given folders and every sub-folder of them."""
    from filer.models import Folder

    ids = [r for r in roots if r is not None]
    level = list(ids)
    for _ in range(10):
        if not level:
            break
        level = list(Folder.objects.filter(parent_id__in=level).values_list("pk", flat=True))
        ids += level
    return ids


def metering_folder_ids(metering) -> list[int]:
    """The metering's folder and every sub-folder of it."""
    if metering.folder_id is None:
        return []
    return folder_tree_ids([metering.folder_id])


def metering_files(metering):
    from filer.models import File

    return File.objects.filter(folder_id__in=metering_folder_ids(metering)).select_related("owner")


def finish_metering(
    metering,
    *,
    by,
    note,
    next_step,
    designer=None,
    pricer=None,
    manager=None,
    design_due_at=None,
    price_due_at=None,
):
    """«Bajarildi»: after measuring, the measurer uploads the files on the site, writes
    the note and picks the next step - design + price or only the price - the designer
    (preselected when there is one) and the manager, who calculates the price (owner's
    rule: no separate pricer; `pricer` is a legacy override) and shows the result to the
    client, and the
    deadlines (default: design 2 days, price 1 day at OFFER_DUE_HOUR). With design +
    price both start at once, each with its own deadline. Returns {"metering", "assigned"}."""
    from django.db import transaction

    from call_center.services import log_metering
    from core.exceptions import ServiceConflict, ServiceError, ServiceForbidden

    from . import events
    from .constants import NextStep

    note = (note or "").strip()
    with transaction.atomic():
        locked = _lock(metering)
        if not can_work_metering(by, locked):
            raise ServiceForbidden("Bu zamer sizga biriktirilmagan")
        if locked.status == MeteringStatus.done:
            raise ServiceConflict("Allaqachon bajarilgan")
        if locked.status != MeteringStatus.metering_done:
            raise ServiceError("Avval «O'lchov oldim» tugmasini bosing")
        if not note:
            raise ServiceError("Natija haqida izoh yozing", "note")
        if next_step not in NextStep.values:
            raise ServiceError("Keyingi bosqichni tanlang", "next_step")
        if next_step == NextStep.design_price and designer is None:
            designer = default_designer()
            if designer is None:
                raise ServiceError(
                    "Dizaynerni tanlang"
                    if designers().exists()
                    else "Dizayner yo'q — Xodimlar → Lavozimlar: «Dizayner» lavozimiga xodim qo'shing",
                    "designer",
                )
        if next_step == NextStep.price and designer is not None:
            raise ServiceError("«Faqat narx» uchun dizayner tanlanmaydi", "designer")
        manager = _pick_manager(manager)
        # the price is the manager's job: the chosen manager calculates it
        if pricer is None:
            if manager is None:
                raise ServiceError(
                    "Menejer yo'q — Xodimlar → Lavozimlar: «Menejer» lavozimiga xodim qo'shing",
                    "manager",
                )
            if not pricers().filter(pk=manager.pk).exists():
                raise ServiceError(
                    "Bu menejerda narx huquqi yo'q — Xodimlar → Lavozimlar: "
                    "lavozimida «Narx» bo'limini (o'zgartirish) yoqing",
                    "manager",
                )
            pricer = manager
        now = _now()
        defaults = offer_defaults(now)
        if next_step == NextStep.design_price:
            design_due_at = _future_due(design_due_at, defaults["design_due_at"], now, "design_due")
        else:
            design_due_at = None
        price_due_at = _future_due(price_due_at, defaults["price_due_at"], now, "price_due")
        if not metering_files(locked).exists():
            raise ServiceError("Kamida bitta fayl yuklang", "files")
        # the offer rows read the manager from the database
        locked.manager = manager
        locked._history_user = by
        locked.save(update_fields=["manager"])
        # BEFORE the status change: it only accepts metering_done / done
        assigned = assign_metering_tasks(
            locked,
            designer=designer,
            pricer=pricer,
            design_due_at=design_due_at,
            price_due_at=price_due_at,
            by=by,
        )
        locked.status = MeteringStatus.done
        locked.result_note = note
        locked.next_step = next_step
        locked.done_at = now
        locked.done_by = by
        locked.rev += 1
        locked._history_user = by
        locked.save(
            update_fields=["status", "result_note", "next_step", "done_at", "done_by", "rev"]
        )
        _bump(
            metering,
            locked,
            ["status", "result_note", "next_step", "done_at", "done_by", "rev", "manager"],
        )
        if locked.invoice_id is not None:
            log_metering(
                locked.invoice,
                author=by,
                event="done",
                text=note,
                meta={"metering_id": locked.pk, "next_step": next_step},
            )
        events.metering_changed(locked, how="done", by=by, to_users=[locked.measurer])
    return {"metering": metering, "assigned": assigned}


def save_metering_files(metering, uploads, *, by):
    """Photos / videos / PDFs of the measurement, into the metering's folder. Only on the
    site (never through the bot)."""
    from api.views.files import save_uploads
    from core.exceptions import ServiceError, ServiceForbidden

    if not can_reschedule_or_cancel(by, metering):
        raise ServiceForbidden("Bu zamerga fayl yuklash huquqi yo'q")
    if metering.status in (MeteringStatus.dont_need, MeteringStatus.sold_out):
        raise ServiceError("Bu zamer yopilgan")
    if metering.folder is None:
        # an older zamer without a folder: make it on a fresh locked row, so the full
        # save inside create_folder can't put back a stale status / rev / date_time
        from django.db import transaction

        from core.utils import create_folder

        with transaction.atomic():
            locked = _lock(metering)
            if locked.status in (MeteringStatus.dont_need, MeteringStatus.sold_out):
                raise ServiceError("Bu zamer yopilgan")
            if locked.folder_id is None:
                locked._history_user = by
                create_folder(locked, "Замер")
        metering.folder_id = locked.folder_id
        metering.folder = locked.folder
        if metering.folder is None:
            raise ServiceError("Zamer papkasi topilmadi")
    limit = METERING_MAX_UPLOAD_MB * 1024 * 1024
    for upload in uploads:
        if upload.size > limit:
            raise ServiceError(
                f"«{upload.name}» juda katta (maks. {METERING_MAX_UPLOAD_MB} MB)", "files"
            )
    return save_uploads(metering.folder, uploads, owner=by)


# --- Zamer stage 1: reads -------------------------------------------------------------


def metering_queryset_for(user, qs=None):
    """Row scoping: a plain measurer sees only their own meterings; managers, superusers
    and everyone else with view_metering see all."""
    from oauth.constants import METERING_PERMISSION

    from .models import Metering

    qs = Metering.objects.all() if qs is None else qs
    if (
        user.has_perm(f"oauth.{METERING_PERMISSION}")
        and not user.is_superuser
        and not user.has_perm(f"metering.{METERING_MANAGE_PERMISSION}")
    ):
        return qs.filter(Q(measurer=user) | Q(measurer__isnull=True))
    return qs


def _late_after():
    from datetime import timedelta

    from constance import config

    return timedelta(minutes=int(config.METERING_LATE_AFTER_MIN))


def is_overdue(metering, now, late_after=None) -> bool:
    """`late_after`: pass the (cached) threshold when checking many rows."""
    if metering.status not in OPEN_STATUSES:
        return False
    if metering.date_time is None:
        return True
    return metering.date_time + (late_after if late_after is not None else _late_after()) <= now


AGENDA_LIMIT = 200
# Older unanswered meterings drop out of «Javob kutilmoqda» (still found via archive/search).
OVERDUE_WINDOW_DAYS = 30


def metering_agenda(qs, *, now) -> dict:
    """The day agenda of the «Zamerlar» page. Lists are ordered by time; `week` is a
    rolling 7 days and overlaps today / tomorrow on purpose."""
    from datetime import timedelta

    from django.db.models import F, Q

    late = now - _late_after()
    today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow0 = today0 + timedelta(days=1)
    open_qs = qs.filter(status__in=OPEN_STATUSES)
    buckets = {
        "overdue": open_qs.filter(
            Q(date_time__isnull=True)
            | Q(date_time__lte=late, date_time__gte=now - timedelta(days=OVERDUE_WINDOW_DAYS))
        ),
        "today": open_qs.filter(date_time__gt=late, date_time__lt=tomorrow0),
        "tomorrow": open_qs.filter(
            date_time__gte=tomorrow0, date_time__lt=tomorrow0 + timedelta(days=1)
        ),
        "week": open_qs.filter(date_time__gt=late, date_time__lt=today0 + timedelta(days=7)),
    }
    out = {"counts": {}}
    for key, bucket in buckets.items():
        out["counts"][key] = bucket.count()
        out[key] = list(bucket.order_by(F("date_time").asc(nulls_first=True), "pk")[:AGENDA_LIMIT])
    waiting = qs.filter(status=MeteringStatus.metering_done)
    out["counts"]["waiting"] = waiting.count()
    out["waiting"] = list(
        waiting.order_by(F("measured_at").asc(nulls_last=True), "pk")[:AGENDA_LIMIT]
    )
    out["counts"]["archive"] = qs.filter(status__in=MeteringStatus.archive_statuses()).count()
    return out


def due_metering_reminders(now) -> dict:
    """Bot reminders for measurers: ~1h before (soon), a nudge when the time passed with
    no answer (late), and the evening list of tomorrow (digest). Each fires once per
    metering revision (accounting.services.once)."""
    from datetime import timedelta

    from constance import config
    from django.db.models import F

    from accounting.services import once

    from . import events
    from .models import Metering

    before = timedelta(minutes=int(config.METERING_REMIND_BEFORE_MIN))
    late_after = _late_after()
    base = (
        Metering.objects.filter(
            status__in=OPEN_STATUSES,
            measurer__isnull=False,
            measurer__is_active=True,
            measurer__telegram_id__isnull=False,
        )
        .select_related("client", "measurer", "created_by", "invoice__assigned_to")
        .order_by("date_time", "pk")
    )
    sent = {"soon": 0, "late": 0, "digest": 0}

    soon = base.filter(
        date_time__gt=now,
        date_time__lte=now + before,
        scheduled_at__lte=F("date_time") - before,
    )
    for m in soon[:200]:
        if once(f"met:{m.pk}:r{m.rev}:soon"):
            events.metering_reminder(m, kind="soon")
            sent["soon"] += 1

    late = base.filter(
        date_time__gte=now - timedelta(hours=24),
        date_time__lte=now - late_after,
        scheduled_at__lt=F("date_time"),
    )
    for m in late[:200]:
        if once(f"met:{m.pk}:r{m.rev}:late"):
            events.metering_reminder(m, kind="late")
            sent["late"] += 1

    if now.hour >= int(config.METERING_DIGEST_HOUR):
        tomorrow0 = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        rows = list(
            base.filter(date_time__gte=tomorrow0, date_time__lt=tomorrow0 + timedelta(days=1))
        )
        per_user = {}
        for m in rows:
            per_user.setdefault(m.measurer_id, []).append(m)
        for items in per_user.values():
            user = items[0].measurer
            if once(f"met:digest:{tomorrow0.date().isoformat()}:{user.pk}"):
                events.metering_digest(user, items, day=tomorrow0.date())
                sent["digest"] += 1
    return sent


def start_design(metering, *, by=None):
    """The legacy «Create design» button: an unassigned design with the default deadline
    (anyone with oauth.user_design may work it; no bot task without an assignee)."""
    from core.exceptions import ServiceError

    from .design.models import Design
    from .design.services import create_design

    if Design.objects.filter(metering=metering).exists():
        raise ServiceError("Dizayn allaqachon yaratilgan")
    _refuse_if_declined(metering, None)
    now = _now()
    return create_design(
        metering, user=None, due_at=default_due(_cfg("DESIGN_DAYS"), now=now), by=by
    )


def start_price(metering, *, by=None):
    from core.exceptions import ServiceError

    from .constants import PRICE_ESTIMATE
    from .price.models import Price
    from .price.services import create_price

    existing = Price.objects.filter(metering=metering).first()
    if existing is not None and existing.stage != PRICE_ESTIMATE:
        raise ServiceError("Narx hisoblash allaqachon yaratilgan")
    from .design.models import Design

    design = Design.objects.filter(metering=metering).first()
    _refuse_if_declined(metering, design, price=True)
    now = _now()
    days = _cfg("PRICE_DAYS")
    due = default_due(days, now=now)
    if existing is not None:  # the lead's approximate price becomes the price task
        from django.db import transaction

        from .price.services import estimate_to_task

        with transaction.atomic():
            _, _, locked = _lock_offer(metering)
            if locked is None or locked.stage != PRICE_ESTIMATE:
                raise ServiceError("Narx hisoblash allaqachon yaratilgan")
            return estimate_to_task(locked, user=None, due_at=due, days=days, by=by)
    return create_price(metering, user=None, due_at=due, days=days, by=by)


# --- Assigning the design / price tasks after the metering --------------------------

ASSIGNABLE_STATUSES = [MeteringStatus.metering_done, MeteringStatus.done]


def designers():
    """Who may be picked to draw the design: active staff holding oauth.user_design
    EXPLICITLY (own or via a group, no superusers) who can also open the design page the
    Telegram link points to."""
    from oauth.constants import DESIGN_PERMISSION
    from oauth.services import users_with_perm

    can_open = users_with_perm("design", "view_design").values("pk")
    return _explicit_holders("oauth", DESIGN_PERMISSION).filter(pk__in=can_open)


def default_designer():
    """The designer when there is exactly one (preselected), else None."""
    found = list(designers()[:2])
    return found[0] if len(found) == 1 else None


def pricers():
    """Who may calculate the price: active staff holding price.change_price EXPLICITLY
    (own or via a group, no superusers) who can open it. Owner's rule: the price is the
    managers' job - «Menejer» / «Bosh menejer» hold these rights (oauth 0013) and
    «Bajarildi» gives the price to the chosen manager."""
    from oauth.services import users_with_perm

    can_open = users_with_perm("price", "view_price").values("pk")
    return _explicit_holders("price", "change_price").filter(pk__in=can_open)


def _refuse_if_declined(metering, design, *, price=False):
    """No design / price work on a metering the client has refused, nor a price after the
    design was declined or cancelled."""
    from core.exceptions import ServiceError

    from .constants import ClientResult, OfferStage

    if metering.client_result in (ClientResult.design_declined, ClientResult.price_declined):
        raise ServiceError("Mijoz rad etgan — vazifa tayinlab bo'lmaydi")
    if price and design is not None and design.stage in (OfferStage.declined, OfferStage.cancelled):
        raise ServiceError("Dizayn rad etilgan yoki bekor qilingan — narx hisoblab bo'lmaydi")


def assign_metering_tasks(
    metering,
    *,
    designer=None,
    pricer=None,
    design_due_at=None,
    price_due_at=None,
    by=None,
) -> dict:
    """After "Замер выполнен": give the design and/or the price task to one person each.

    Owner's rule: the metering staff hand these tasks out themselves, so this creates
    the Design / Price rows without design.add_design / price.add_price.

    A task that doesn't exist yet is created for that person; an existing unfinished
    task is handed over to the new person (the old one's bot card is retired). Design and
    price start at the same time, each person is told at once. Only the chosen people are notified, and only after the whole
    change is committed — a refused or failed request sends nothing.
    Returns {"design": "created"|"reassigned"|None, "price": ...}.
    """
    from django.db import IntegrityError, transaction

    from core.exceptions import ServiceError

    from .constants import PRICE_ESTIMATE, OfferStage
    from .design.services import create_design
    from .price.services import create_price, estimate_to_task

    if designer is None and pricer is None:
        raise ServiceError("Dizayner va/yoki narx hisoblovchini tanlang")
    if designer is not None and not designers().filter(pk=designer.pk).exists():
        raise ServiceError("Bu xodim dizayn qila olmaydi")
    if pricer is not None and not pricers().filter(pk=pricer.pk).exists():
        raise ServiceError("Bu xodim narx hisoblay olmaydi")

    result = {"design": None, "price": None}
    try:
        with transaction.atomic():
            # Serialises concurrent assigns of the same metering.
            locked, design, price = _lock_offer(metering)
            if locked.status not in ASSIGNABLE_STATUSES:
                raise ServiceError("Ijrochilar «O'lchov bajarildi»dan keyin tayinlanadi")
            # Every refusal before any write.
            _refuse_if_declined(locked, design, price=pricer is not None)
            if designer is not None and design is not None:
                if design.done:
                    raise ServiceError("Dizayn allaqachon bajarilgan — qayta tayinlab bo'lmaydi")
                if design.stage != OfferStage.work:
                    raise ServiceError("Dizayn yopilgan — qayta tayinlab bo'lmaydi")
            estimate = price is not None and price.stage == PRICE_ESTIMATE
            if pricer is not None and price is not None and not estimate:
                if price.done:
                    raise ServiceError("Narx allaqachon hisoblangan — qayta tayinlab bo'lmaydi")
                if price.stage != OfferStage.work:
                    raise ServiceError("Narx yopilgan — qayta tayinlab bo'lmaydi")

            now = _now()
            if designer is not None:
                if design is None:
                    due = design_due_at or default_due(_cfg("DESIGN_DAYS"), now=now)
                    design = create_design(locked, user=designer, due_at=due, by=by)
                    result["design"] = "created"
                elif design.user_id != designer.pk:
                    _hand_over(design, "design", designer, by=by, now=now)
                    result["design"] = "reassigned"
            if pricer is not None:
                if price is None or estimate:
                    days = _cfg("PRICE_DAYS")
                    due = price_due_at or default_due(days, now=now)
                    if estimate:  # the lead's approximate price: the manager finishes it
                        estimate_to_task(price, user=pricer, due_at=due, days=days, by=by)
                        result["price"] = "from_estimate"
                    else:
                        create_price(locked, user=pricer, due_at=due, days=days, by=by)
                        result["price"] = "created"
                elif price.user_id != pricer.pk:
                    _hand_over(price, "price", pricer, by=by, now=now)
                    result["price"] = "reassigned"
    except IntegrityError:
        raise ServiceError("Vazifalar hozir tayinlanmoqda — sahifani yangilang")
    return result


# --- Stage 2: dizayn va narx ----------------------------------------------------------
# Docs: docs/BOT_CONTRACT.md, "Dizayn va narx". Lock order: Invoice -> Metering -> Design
# -> Price -> InvoiceTask (_lock_offer).

PRESENT_LOOKBACK_DAYS = 7
_DUE_PRESETS = {"1d": 1, "2d": 2, "3d": 3}
_PAST = "O'tgan vaqt — kelajakdagi vaqtni kiriting"


def _cfg(name):
    from constance import config

    return int(getattr(config, name))


def managers():
    """Who may show the design / price to the client (and, owner's rule, calculate the
    price): active staff holding metering.present_to_client EXPLICITLY (like
    measurers(): no superusers). «Menejer» and «Bosh menejer» both hold it (oauth 0013)."""
    from .constants import METERING_PRESENT_PERMISSION

    return _explicit_holders("metering", METERING_PRESENT_PERMISSION)


def bosses():
    """«Bosh menejer»: active staff holding metering.manage_metering EXPLICITLY. They get
    a copy of the managers' bot cards (price task, «tayyor», «buyurtma yarating»)."""
    return _explicit_holders("metering", METERING_MANAGE_PERMISSION)


def default_manager():
    """The manager when there is exactly one (preselected), else None. A «Bosh menejer»
    (manage_metering) does not count when there is exactly one plain «Menejer»: they
    get a copy of every card anyway (oauth 0013 made them managers too)."""
    plain = list(managers().exclude(pk__in=bosses().order_by().values("pk"))[:2])
    if len(plain) == 1:
        return plain[0]
    found = list(managers()[:2])
    return found[0] if len(found) == 1 else None


def order_creators():
    """Who is told to make the order when the client agreed to the price: active staff
    holding order.add_order EXPLICITLY."""
    return _explicit_holders("order", "add_order")


def manager_of(metering):
    """Who gets the «ready» card of this metering: its manager; a legacy row without one
    goes to the only manager, else to nobody."""
    return metering.manager or default_manager()


def default_due(days, *, now):
    from datetime import datetime, time, timedelta

    return datetime.combine(now.date() + timedelta(days=days), time(_cfg("OFFER_DUE_HOUR")))


def offer_defaults(now) -> dict:
    return {
        "design_due_at": default_due(_cfg("DESIGN_DAYS"), now=now),
        "price_due_at": default_due(_cfg("PRICE_DAYS"), now=now),
    }


def shift_due(current, *, now, preset=None, text=None, due_at=None):
    """The new deadline. Exactly one of preset ("1d"|"2d"|"3d": that many days after the
    later of the old deadline's day and today, same clock), text ("18:00", "25.12",
    "25.12 18:00") or due_at. Must be in the future."""
    from datetime import datetime, time, timedelta

    from call_center.services import parse_due
    from core.exceptions import ServiceError

    text = (text or "").strip() or None
    if sum(x is not None for x in (preset, text, due_at)) != 1:
        raise ServiceError("Yangi muddatni kiriting", "due")
    clock = (
        current.time().replace(second=0, microsecond=0)
        if current is not None
        else time(_cfg("OFFER_DUE_HOUR"))
    )
    if due_at is not None:
        target = due_at.replace(second=0, microsecond=0)
    elif preset is not None:
        if preset not in _DUE_PRESETS:
            raise ServiceError("Noma'lum muddat tanlovi", "due")
        base = max(current.date(), now.date()) if current is not None else now.date()
        target = datetime.combine(base + timedelta(days=_DUE_PRESETS[preset]), clock)
    else:
        try:
            target = parse_due(text, now, default_time=clock)
        except ServiceError as e:
            raise ServiceError(e.message, "due")
    if target <= now:
        raise ServiceError(_PAST, "due")
    return target


def _future_due(value, default, now, field):
    from core.exceptions import ServiceError

    if value is None:
        return default
    value = value.replace(second=0, microsecond=0)
    if value <= now:
        raise ServiceError(_PAST, field)
    return value


def _pick_manager(manager):
    """«Bajarildi» needs a manager once one exists; exactly one is preselected. With no
    manager at all (rollout) it finishes without one (None) and logs a warning."""
    from core.exceptions import ServiceError

    if manager is None:
        manager = default_manager()
        if manager is None:
            if managers().exists():
                raise ServiceError("Menejerni tanlang", "manager")
            import logging

            logging.getLogger("metering").warning(
                "finish without a manager: nobody holds metering.present_to_client"
            )
            return None
        return manager
    if not managers().filter(pk=manager.pk).exists():
        raise ServiceError("Bu xodim menejer emas", "manager")
    return manager


def can_present(user, metering) -> bool:
    """May record the client's answer for this metering."""
    from .constants import METERING_PRESENT_PERMISSION

    if user is None:
        return False
    if user.is_superuser or user.has_perm(f"metering.{METERING_MANAGE_PERMISSION}"):
        return True
    if metering.manager_id is not None:
        return metering.manager_id == user.pk
    return user.has_perm(f"metering.{METERING_PRESENT_PERMISSION}")


def _lock_offer(metering):
    """Lock the metering (after its lead), then its Design, then its Price. Returns
    (metering, design|None, price|None); each offer row has the locked metering attached."""
    from .design.models import Design
    from .price.models import Price

    locked = _lock(metering)
    design = (
        Design.objects.select_for_update(of=("self",))
        .select_related("user")
        .filter(metering=locked)
        .first()
    )
    price = (
        Price.objects.select_for_update(of=("self",))
        .select_related("user")
        .filter(metering=locked)
        .first()
    )
    for row in (design, price):
        if row is not None:
            row.metering = locked
    return locked, design, price


def _copy_back(obj, locked, fields):
    for name in fields:
        setattr(obj, name, getattr(locked, name))
    return obj


def _hand_over(obj, kind, user, *, by, now):
    """Give an unfinished Design / Price to another person: the old one's bot card is
    retired, the new one gets the task."""
    from . import events

    old = obj.user
    obj.user = user
    obj.rev += 1
    fields = ["user", "rev"]
    if obj.stage == "work":
        obj.assigned_at = now
        fields.append("assigned_at")
    obj._history_user = by
    obj.save(update_fields=fields)
    if obj.stage == "work":
        events.offer_changed(
            obj,
            kind,
            how="reassigned",
            by=by,
            to_users=[old] if old is not None else [],
            to_name=_name(user),
        )
        events.offer_assigned(obj, kind, how="reassigned")
        queue_offer_sms(obj, kind, "assigned")


def queue_offer_sms(obj, kind, what):
    """SMS (after commit, via Celery) for a person without Telegram. what: "assigned"
    (the designer / pricer) | "ready" (the manager)."""
    from django.db import transaction

    person = obj.user if what == "assigned" else manager_of(obj.metering)
    if person is None or person.telegram_id or not person.is_active:
        return
    oid, rev = obj.pk, obj.rev

    def _go():
        try:
            from .tasks import offer_sms

            offer_sms.delay(kind, oid, rev, what)
        except Exception:  # noqa: BLE001 - a broken broker must not undo the change
            import logging

            logging.getLogger("metering").exception("could not queue the offer SMS")

    transaction.on_commit(_go)


def folder_file_count(folder_ids) -> int:
    from filer.models import File

    return File.objects.filter(folder_id__in=folder_tree_ids(folder_ids)).count()


def offer_stage_error(stage):
    """The refusal for a Design / Price that cannot be worked any more."""
    from core.exceptions import ServiceConflict

    if stage in ("review", "approved"):
        return ServiceConflict("Allaqachon bajarilgan")
    return ServiceConflict("Bu vazifa yopilgan")


# --- Stage 2: reads -------------------------------------------------------------------


def due_offer_reminders(now) -> dict:
    """Bot reminders for the designer / pricer (soon, late, daily overdue) and for the
    manager who owes the client's answer (nudge, then daily). Each fires once per
    revision of the row (accounting.services.once)."""
    from datetime import datetime, time, timedelta

    from accounting.services import once

    from . import events
    from .design.models import Design
    from .price.models import Price

    hour = _cfg("OFFER_REMIND_HOUR")
    today_at = datetime.combine(now.date(), time(hour))
    present_after = timedelta(hours=_cfg("PRESENT_REMIND_HOURS"))
    sent = {"soon": 0, "late": 0, "overdue": 0, "present": 0}
    midnight = datetime.combine(now.date(), time(0))
    fallback_manager = default_manager()  # once per run, not per row

    def remind_at(obj):
        due = obj.due_at
        if obj.assigned_at is not None and due - obj.assigned_at >= timedelta(hours=36):
            at = datetime.combine(due.date() - timedelta(days=1), time(hour))
        else:
            at = datetime.combine(due.date(), time(hour))
        return at if at < due else due - timedelta(hours=2)

    for model, kind in ((Design, "design"), (Price, "price")):
        key = f"off:{kind[0]}"
        work = (
            model.objects.filter(
                stage="work",
                due_at__isnull=False,
                user__isnull=False,
                user__is_active=True,
                user__telegram_id__isnull=False,
            )
            .select_related("metering__client", "metering__manager", "metering__measurer", "user")
            .order_by("due_at", "pk")
        )
        # soon: the reminder moment has come, the deadline has not
        count = 0
        for obj in work.filter(due_at__gt=now, due_at__lte=now + timedelta(days=3))[:1000]:
            at = remind_at(obj)
            if obj.assigned_at is not None and not obj.assigned_at < at:
                continue  # assigned after the reminder moment: nothing to remind of yet
            if at <= now and count < 200 and once(f"{key}:{obj.pk}:r{obj.rev}:soon"):
                events.offer_reminder(obj, kind, what="soon")
                sent["soon"] += 1
                count += 1
        # late: the deadline just passed
        for obj in work.filter(due_at__lte=now, due_at__gte=now - timedelta(hours=24))[:200]:
            if once(f"{key}:{obj.pk}:r{obj.rev}:late"):
                events.offer_reminder(obj, kind, what="late")
                sent["late"] += 1
        # overdue: every morning for a week
        if now >= today_at:
            # from the NEXT day after the deadline: a deadline before the reminder hour has
            # just got its "late" - no "overdue" an hour later the same day
            late = work.filter(due_at__lt=midnight, due_at__gte=now - timedelta(days=7))
            for obj in late[:200]:
                if once(f"{key}:{obj.pk}:r{obj.rev}:od:{now.date().isoformat()}"):
                    events.offer_reminder(obj, kind, what="overdue")
                    sent["overdue"] += 1
        # manager: the client's answer is overdue
        review = (
            model.objects.filter(
                stage="review",
                done_at__lte=now - present_after,
                done_at__gt=now - present_after - timedelta(days=PRESENT_LOOKBACK_DAYS),
            )
            .select_related("metering__client", "metering__manager", "metering__measurer", "user")
            .order_by("done_at", "pk")
        )
        for obj in review[:200]:
            who = obj.metering.manager or fallback_manager
            if who is None or not who.is_active or not who.telegram_id:
                continue
            day = f"{key}:{obj.pk}:r{obj.rev}:pr:{now.date().isoformat()}"
            if once(f"{key}:{obj.pk}:r{obj.rev}:pr"):
                once(day)  # the first nudge is today's
            elif now < today_at or not once(day):
                continue
            events.offer_present(obj, kind, how="reminder", to_users=[who])
            sent["present"] += 1
    return sent


def offer_agenda(qs, *, now, split_ordered=False) -> dict:
    """The agenda of the «Dizayn» / «Narx hisoblash» page over `qs` (Design or Price rows).
    overdue = in work past the deadline; today = in work due today; work = all in work
    (nearest deadline first, undated last); review = waiting for the client's answer.
    The archive is paged by the list. split_ordered (the «Dizayn» page): the archive is
    shown in two parts - «ordered» = every row whose zamer already became an order (any
    stage), «archive» = the archive-stage rows without an order."""
    from datetime import timedelta

    from django.db.models import F

    from .constants import OFFER_ARCHIVE

    today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    work = qs.filter(stage="work")
    buckets = {
        "overdue": work.filter(due_at__lt=now).order_by("due_at", "pk"),
        "today": work.filter(due_at__gte=now, due_at__lt=today0 + timedelta(days=1)).order_by(
            "due_at", "pk"
        ),
        "work": work.order_by(F("due_at").asc(nulls_last=True), "pk"),
        "review": qs.filter(stage="review").order_by(F("done_at").asc(nulls_last=True), "pk"),
    }
    out = {"counts": {}}
    for key, bucket in buckets.items():
        out["counts"][key] = bucket.count()
        out[key] = list(bucket[:AGENDA_LIMIT])
    archive = qs.filter(stage__in=OFFER_ARCHIVE)
    if split_ordered:
        out["counts"]["ordered"] = qs.filter(metering__order__isnull=False).count()
        archive = archive.filter(metering__order__isnull=True)
    out["counts"]["archive"] = archive.count()
    return out


def offer_queryset_for(user, qs, *, kind):
    """Row scoping of the AGENDA: a plain designer / pricer sees only their own rows;
    manage_metering («Bosh menejer») and superusers see all. (List and detail are scoped
    by the viewset as before.)"""
    if user.is_superuser or user.has_perm(f"metering.{METERING_MANAGE_PERMISSION}"):
        return qs
    return qs.filter(user=user)


def presentations(user, *, now, manager=None, search="") -> dict:
    """«Mijozga ko'rsatish»: what the manager owes the client. Rows are dicts
    {metering, design, price, manager, waiting_for, is_overdue}. Scope: my meterings (and
    those with no manager yet); everything for manage_metering and superusers.
    review = the design / price is ready, the client's answer is due; working = the
    designer / pricer is still at it; order_ready = the client agreed, no order yet.
    `manager` (a user id) and `search` narrow the queryset BEFORE the row cap; `counts`
    are of the whole filtered set, not of the capped rows."""
    from datetime import timedelta

    from django.db.models import Prefetch, Q

    from .constants import ClientResult
    from .models import Metering, OfferAnswer

    present_after = timedelta(hours=_cfg("PRESENT_REMIND_HOURS"))
    cut = now - present_after

    def rows(qs, bucket):
        out = []
        for m in qs.order_by("-pk")[:AGENDA_LIMIT]:
            design = getattr(m, "design", None)
            price = getattr(m, "price", None)
            waiting_for = None
            overdue = False
            if bucket == "review":
                done = [
                    o.done_at for o in (design, price) if o and o.stage == "review" and o.done_at
                ]
                overdue = bool(done) and min(done) + present_after <= now
            elif bucket == "working":
                if design is not None and design.stage == "work":
                    waiting_for = "design"
                elif price is not None and price.stage == "work":
                    waiting_for = "price"
                overdue = any(
                    o is not None and o.stage == "work" and o.due_at and o.due_at < now
                    for o in (design, price)
                )
            out.append(
                {
                    "metering": m,
                    "design": design,
                    "price": price,
                    "manager": m.manager,
                    "waiting_for": waiting_for,
                    "is_overdue": overdue,
                }
            )
        return out

    base = Metering.objects.filter(status=MeteringStatus.done)
    if not (user.is_superuser or user.has_perm(f"metering.{METERING_MANAGE_PERMISSION}")):
        base = base.filter(Q(manager=user) | Q(manager__isnull=True))
    if manager is not None:
        base = base.filter(manager_id=manager)
    search = (search or "").strip()
    if search:
        base = base.filter(
            Q(client__fio__icontains=search)
            | Q(client__phone__icontains=search)
            | Q(address__icontains=search)
        )
    in_review = Q(design__stage="review") | Q(price__stage="review")
    in_work = Q(design__stage="work") | Q(price__stage="work")
    review = base.filter(in_review)
    working = base.filter(in_work).exclude(in_review)
    ready = base.filter(client_result=ClientResult.agreed, order__isnull=True)
    late_review = review.filter(
        Q(design__stage="review", design__done_at__lte=cut)
        | Q(price__stage="review", price__done_at__lte=cut)
    )
    late_working = working.filter(
        Q(design__stage="work", design__due_at__lt=now)
        | Q(price__stage="work", price__due_at__lt=now)
    )

    def heavy(qs):
        return qs.select_related(
            "client", "manager", "measurer", "design__user", "price__user"
        ).prefetch_related(
            "design__designtype_set",
            Prefetch("offer_answers", queryset=OfferAnswer.objects.order_by("created_at", "pk")),
        )

    return {
        "review": rows(heavy(review), "review"),
        "working": rows(heavy(working), "working"),
        "order_ready": rows(heavy(ready), "order_ready"),
        "counts": {
            "review": review.count(),
            "overdue": late_review.count() + late_working.count(),
            "working": working.count(),
            "order_ready": ready.count(),
        },
    }


# --- Stage 2: writes shared by Design and Price ----------------------------------------


def offer_locked(obj, kind):
    """(metering, design, price, row): all locked in the global order; `row` is `obj`'s
    row. Call inside transaction.atomic()."""
    from core.exceptions import ServiceError

    m, design, price = _lock_offer(obj.metering)
    row = design if kind == "design" else price
    if row is None or row.pk != obj.pk:
        raise ServiceError("Vazifa topilmadi")
    return m, design, price, row


def move_offer_due(obj, kind, *, by, can_work, due_at=None, preset=None, text=None):
    """Move the deadline of a task in work (the assignee, a boss or a zamer manager).
    The assignee's bot card is re-rendered; the manager is told when someone else moved it."""
    from django.db import transaction

    from core.exceptions import ServiceConflict, ServiceForbidden

    from . import events

    with transaction.atomic():
        m, _, _, row = offer_locked(obj, kind)
        if not (can_work(by, row) or by.has_perm(f"metering.{METERING_MANAGE_PERMISSION}")):
            raise ServiceForbidden("Bu vazifa sizga biriktirilmagan")
        if row.stage != "work":
            raise ServiceConflict("Muddatni faqat ishdagi vazifada o'zgartirish mumkin")
        row.due_at = shift_due(row.due_at, now=_now(), preset=preset, text=text, due_at=due_at)
        row.rev += 1
        row._history_user = by
        row.save(update_fields=["due_at", "rev"])
        watchers = [m.manager] if m.manager is not None and m.manager.pk != by.pk else []
        events.offer_changed(
            row,
            kind,
            how="due_moved",
            by=by,
            to_users=[row.user] if row.user is not None else [],
            watchers=watchers,
        )
    return _copy_back(obj, row, ["due_at", "rev"])


def reassign_offer(obj, kind, *, by, user, boss_perm, pool):
    """Hand a task in work to another person."""
    from django.db import transaction

    from core.exceptions import ServiceError, ServiceForbidden

    with transaction.atomic():
        _, _, _, row = offer_locked(obj, kind)
        if not (
            by.is_superuser
            or by.has_perm(boss_perm)
            or by.has_perm(f"metering.{METERING_MANAGE_PERMISSION}")
        ):
            raise ServiceForbidden("Ijrochini almashtirish huquqi yo'q")
        if not pool.filter(pk=user.pk).exists():
            raise ServiceError("Bu xodim bu ishni bajara olmaydi", "user")
        if row.stage != "work":
            raise offer_stage_error(row.stage)
        if row.user_id != user.pk:
            _hand_over(row, kind, user, by=by, now=_now())
    return _copy_back(obj, row, ["user", "rev", "assigned_at"])


def offer_ready(row, kind, m, *, by, now):
    """The designer / pricer pressed «Tayyor»: the task goes to the manager. Inside the
    caller's transaction, row locked."""
    from call_center.services import log_metering

    from . import events

    row.done = True
    row.stage = "review"
    row.done_at = now
    row.done_by = by
    row.rev += 1
    row._history_user = by
    row.save(update_fields=["done", "stage", "done_at", "done_by", "rev"])
    if m.invoice_id is not None:
        log_metering(
            m.invoice,
            author=by,
            event=f"{kind}_done",
            meta={"metering_id": m.pk, f"{kind}_id": row.pk, "round": row.round},
        )
    events.offer_changed(
        row, kind, how="done", by=by, to_users=[row.user] if row.user is not None else []
    )
    who = manager_of(m)
    # the Bosh menejer gets a copy even when the row has no manager (events adds them)
    events.offer_present(row, kind, how="ready", to_users=[who] if who is not None else [])
    if who is not None:
        queue_offer_sms(row, kind, "ready")


def offer_answer_prelude(answer, comment, allowed):
    """Validate the manager's answer before any lock: returns the stripped comment."""
    from core.exceptions import ServiceError

    if answer not in allowed:
        raise ServiceError("Javobni tanlang", "answer")
    comment = (comment or "").strip()
    if answer == "declined" and len(comment) < MIN_REASON:
        raise ServiceError("Sababini yozing", "comment")
    if answer in ("changes", "recalc") and len(comment) < MIN_REASON:
        raise ServiceError("Nima o'zgarishini yozing", "comment")
    return comment


def offer_check_answerable(row, m, by, kind):
    """403 not the manager; 409 already answered / closed; 400 not ready yet."""
    from core.exceptions import ServiceConflict, ServiceError, ServiceForbidden

    if not can_present(by, m):
        raise ServiceForbidden("Bu mijoz sizga biriktirilmagan")
    if row.stage in ("approved", "declined"):
        raise ServiceConflict("Javob allaqachon yozilgan")
    if row.stage == "cancelled":
        raise ServiceConflict("Bu vazifa yopilgan")
    if row.stage != "review":
        raise ServiceError(
            "Dizayn hali tayyor emas" if kind == "design" else "Narx hali tayyor emas"
        )


def offer_store_answer(row, kind, m, *, by, answer, comment, round_, due_at=None, log=True):
    """The OfferAnswer row + the lead's timeline line. `round_` = the round that was
    answered (the row's round may already have moved on)."""
    from call_center.services import log_metering

    from .models import OfferAnswer

    OfferAnswer.objects.create(
        metering=m, kind=kind, round=round_, answer=answer, comment=comment, due_at=due_at, by=by
    )
    if log and m.invoice_id is not None:
        log_metering(
            m.invoice,
            author=by,
            event=f"{kind}_{answer}",
            text=comment,
            meta={"metering_id": m.pk, f"{kind}_id": row.pk, "round": round_},
        )


def offer_send_back(row, kind, m, *, by, now, comment, due_at, fix_cfg):
    """«O'zgartirish kerak» / «Qayta hisoblash»: the same assignee works it again."""
    from . import events

    if due_at is not None:
        due_at = _future_due(due_at, None, now, "due")
    else:
        due_at = default_due(_cfg(fix_cfg), now=now)
    row.done = False
    row.stage = "work"
    row.round += 1
    row.assigned_at = now
    row.due_at = due_at
    row.done_at = None
    row.done_by = None
    row.rev += 1
    row._history_user = by
    row.save(
        update_fields=[
            "done",
            "stage",
            "round",
            "assigned_at",
            "due_at",
            "done_at",
            "done_by",
            "rev",
        ]
    )
    events.offer_assigned(row, kind, how="changes", comment=comment)
    return due_at


def offer_answered(row, kind, m, *, by, answer):
    """Tell the manager's chats (also when the answer came from the bot) the card is done."""
    from . import events

    row.rev += 1  # a newer revision than the events above: the bot drops older ones
    row._history_user = by
    row.save(update_fields=["rev"])
    who = manager_of(m)
    events.offer_changed(
        row, kind, how="answered", by=by, answer=answer, to_users=[who] if who else []
    )
    if answer in ("changes", "recalc"):
        # queued only now: the SMS is tied to the FINAL revision (the bump above)
        queue_offer_sms(row, kind, "assigned")


# --- Dashboard: Zamer · Dizayn · Narx overview --------------------------------------


def can_see_pipeline(user) -> bool:
    return bool(user.is_superuser or user.has_perm(f"metering.{METERING_MANAGE_PERMISSION}"))


def pipeline_overview(now, *, limit=10) -> dict:
    """What the bosses see on the home page: counts of zamer / design / price work, the
    most overdue items and the open load per person. A fixed number of queries."""
    from datetime import timedelta

    from django.db.models import Count, Q

    from .constants import ClientResult
    from .design.models import Design
    from .models import Metering
    from .price.models import Price

    def person(pk, name, phone):
        return {"id": pk, "name": name or str(phone or "")} if pk else None

    today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    present_after = timedelta(hours=_cfg("PRESENT_REMIND_HOURS"))
    scheduled = Metering.objects.filter(
        status__in=[MeteringStatus.created, MeteringStatus.other_day]
    )
    z = Metering.objects.aggregate(
        today=Count(
            "pk",
            filter=Q(
                status__in=[MeteringStatus.created, MeteringStatus.other_day],
                date_time__gte=today0,
                date_time__lt=today0 + timedelta(days=1),
            ),
        ),
        overdue=Count(
            "pk",
            filter=Q(
                status__in=[MeteringStatus.created, MeteringStatus.other_day], date_time__lt=now
            ),
        ),
        waiting=Count("pk", filter=Q(status=MeteringStatus.metering_done)),
        ready=Count(
            "pk",
            filter=Q(
                status=MeteringStatus.done,
                client_result=ClientResult.agreed,
                order__isnull=True,
            ),
        ),
    )
    counts = {
        "zamer_today": z["today"],
        "zamer_overdue": z["overdue"],
        "zamer_waiting": z["waiting"],
        "order_ready": z["ready"],
    }
    overdue_rows = []
    load = {}

    for model, kind, role in ((Design, "design", "dizayner"), (Price, "price", "narxchi")):
        agg = model.objects.aggregate(
            work=Count("pk", filter=Q(stage="work")),
            overdue=Count("pk", filter=Q(stage="work", due_at__lt=now)),
            review=Count("pk", filter=Q(stage="review")),
        )
        counts[f"{kind}_work"] = agg["work"]
        counts[f"{kind}_overdue"] = agg["overdue"]
        counts[f"{kind}_review"] = agg["review"]
        for r in (
            model.objects.filter(stage="work")
            .values("user_id", "user__name", "user__phone")
            .annotate(n=Count("pk"), late=Count("pk", filter=Q(due_at__lt=now)))
        ):
            row = load.setdefault(
                (role, r["user_id"]),
                {
                    "role": role,
                    "person": person(r["user_id"], r["user__name"], r["user__phone"]),
                    "open": 0,
                    "overdue": 0,
                },
            )
            row["open"] += r["n"]
            row["overdue"] += r["late"]
        for obj in (
            model.objects.filter(stage="work", due_at__lt=now)
            .select_related("metering__client", "user")
            .order_by("due_at")[:limit]
        ):
            overdue_rows.append(
                {
                    "kind": kind,
                    "id": obj.pk,
                    "client": str(obj.metering.client) if obj.metering else "",
                    "person": person(
                        obj.user_id, obj.user and obj.user.name, obj.user and obj.user.phone
                    ),
                    "due_at": obj.due_at,
                    "late_hours": round((now - obj.due_at).total_seconds() / 3600, 1),
                    "url": f"/{kind}s/{obj.pk}",
                }
            )
        # managers: what they still owe the client
        for r in (
            model.objects.filter(stage="review", metering__manager__isnull=False)
            .values("metering__manager_id", "metering__manager__name", "metering__manager__phone")
            .annotate(n=Count("pk"), late=Count("pk", filter=Q(done_at__lte=now - present_after)))
        ):
            row = load.setdefault(
                ("menejer", r["metering__manager_id"]),
                {
                    "role": "menejer",
                    "person": person(
                        r["metering__manager_id"],
                        r["metering__manager__name"],
                        r["metering__manager__phone"],
                    ),
                    "open": 0,
                    "overdue": 0,
                },
            )
            row["open"] += r["n"]
            row["overdue"] += r["late"]

    for r in (
        Metering.objects.filter(
            status__in=[
                MeteringStatus.created,
                MeteringStatus.other_day,
                MeteringStatus.metering_done,
            ]
        )
        .values("measurer_id", "measurer__name", "measurer__phone")
        .annotate(
            n=Count("pk"),
            late=Count(
                "pk",
                filter=Q(
                    date_time__lt=now, status__in=[MeteringStatus.created, MeteringStatus.other_day]
                ),
            ),
        )
    ):
        load[("zamerchi", r["measurer_id"])] = {
            "role": "zamerchi",
            "person": person(r["measurer_id"], r["measurer__name"], r["measurer__phone"]),
            "open": r["n"],
            "overdue": r["late"],
        }
    for m in (
        scheduled.filter(date_time__lt=now)
        .select_related("client", "measurer")
        .order_by("date_time")[:limit]
    ):
        overdue_rows.append(
            {
                "kind": "zamer",
                "id": m.pk,
                "client": str(m.client),
                "person": person(
                    m.measurer_id, m.measurer and m.measurer.name, m.measurer and m.measurer.phone
                ),
                "due_at": m.date_time,
                "late_hours": round((now - m.date_time).total_seconds() / 3600, 1),
                "url": f"/meterings/{m.pk}",
            }
        )
    overdue_rows.sort(key=lambda r: -r["late_hours"])
    return {
        "counts": counts,
        "overdue": overdue_rows[:limit],
        "load": sorted(
            load.values(),
            key=lambda r: (r["role"], -r["overdue"], -r["open"]),
        ),
    }
