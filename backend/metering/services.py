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
                if old_metering.status != MeteringStatus.dont_need:
                    raise ServiceError("Bu ariza uchun o'lchov allaqachon yaratilgan")
                # Metering.invoice is a OneToOne: a cancelled zamer lets go of the lead so
                # the operator can book a new one.
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


def measurers():
    """Who can be sent to measure: active staff holding oauth.user_metering EXPLICITLY
    (own or via a group). Deliberately not users_with_perm: that adds every superuser."""
    from django.db.models import Q

    from oauth.constants import METERING_PERMISSION
    from oauth.models import User

    perm = Q(
        user_permissions__codename=METERING_PERMISSION,
        user_permissions__content_type__app_label="oauth",
    ) | Q(
        groups__permissions__codename=METERING_PERMISSION,
        groups__permissions__content_type__app_label="oauth",
    )
    return (
        User.objects.filter(is_active=True, is_staff=True)
        .filter(perm)
        .distinct()
        .order_by("name", "phone")
    )


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
    """Row locks in the one global order Invoice -> Metering -> InvoiceTask: the lead's
    row first (when there is one), then the metering."""
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
                locked.invoice, by=by, reason=reason, metering_id=locked.pk
            )
        events.metering_changed(locked, how="cancelled", by=by, to_users=[locked.measurer])
    return metering, returned


def metering_folder_ids(metering) -> list[int]:
    """The metering's folder and every sub-folder of it."""
    from filer.models import Folder

    if metering.folder_id is None:
        return []
    ids, level = [metering.folder_id], [metering.folder_id]
    for _ in range(10):
        level = list(Folder.objects.filter(parent_id__in=level).values_list("pk", flat=True))
        if not level:
            break
        ids += level
    return ids


def metering_files(metering):
    from filer.models import File

    return File.objects.filter(folder_id__in=metering_folder_ids(metering)).select_related("owner")


def finish_metering(metering, *, by, note, next_step, designer=None, pricer=None):
    """«Bajarildi»: after measuring, the measurer uploads the files on the site, writes
    the note and picks the next step - design + price (designer and pricer) or only the
    price (pricer). Returns {"metering", "assigned"}."""
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
        if pricer is None:
            raise ServiceError("Narx hisoblovchini tanlang", "pricer")
        if next_step == NextStep.design_price and designer is None:
            raise ServiceError("Dizaynerni tanlang", "designer")
        if next_step == NextStep.price and designer is not None:
            raise ServiceError("«Faqat narx» uchun dizayner tanlanmaydi", "designer")
        if not metering_files(locked).exists():
            raise ServiceError("Kamida bitta fayl yuklang", "files")
        # BEFORE the status change: it only accepts metering_done / done
        assigned = assign_metering_tasks(locked, designer=designer, pricer=pricer)
        locked.status = MeteringStatus.done
        locked.result_note = note
        locked.next_step = next_step
        locked.done_at = _now()
        locked.done_by = by
        locked.rev += 1
        locked._history_user = by
        locked.save(
            update_fields=["status", "result_note", "next_step", "done_at", "done_by", "rev"]
        )
        _bump(
            metering,
            locked,
            ["status", "result_note", "next_step", "done_at", "done_by", "rev"],
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


def start_design(metering):
    from core.exceptions import ServiceError

    from .design.models import Design

    if Design.objects.filter(metering=metering).exists():
        raise ServiceError("Dizayn allaqachon yaratilgan")
    return Design.objects.create(metering=metering)


def start_price(metering):
    from core.exceptions import ServiceError

    from .price.models import Price

    if Price.objects.filter(metering=metering).exists():
        raise ServiceError("Narx hisoblash allaqachon yaratilgan")
    return Price.objects.create(metering=metering)


# --- Assigning the design / price tasks after the metering --------------------------

ASSIGNABLE_STATUSES = [MeteringStatus.metering_done, MeteringStatus.done]


def designers():
    """Who may be picked to draw the design: design staff who can also open the
    design page the Telegram link points to."""
    from oauth.constants import DESIGN_PERMISSION
    from oauth.services import users_with_perm

    can_open = users_with_perm("design", "view_design").values("pk")
    return (
        users_with_perm("oauth", DESIGN_PERMISSION)
        .filter(pk__in=can_open)
        .order_by("name", "phone")
    )


def pricers():
    """Who may be picked to calculate the price: users who can edit price calculations
    (and open them)."""
    from oauth.services import users_with_perm

    can_open = users_with_perm("price", "view_price").values("pk")
    return (
        users_with_perm("price", "change_price").filter(pk__in=can_open).order_by("name", "phone")
    )


def assign_metering_tasks(metering, *, designer=None, pricer=None) -> dict:
    """After "Замер выполнен": give the design and/or the price task to one person each.

    Owner's rule: the metering staff hand these tasks out themselves, so this creates
    the Design / Price rows without design.add_design / price.add_price.

    A task that doesn't exist yet is created for that person; an existing unfinished
    task is handed over to the new person. Only the chosen people are notified, and only
    after the whole change is committed — a refused or failed request sends nothing.
    Returns {"design": "created"|"reassigned"|None, "price": ...}.
    """
    from django.db import IntegrityError, transaction

    from core.exceptions import ServiceError

    from .design.models import Design
    from .design.services import notify_design_task
    from .price.models import Price
    from .price.services import notify_price_task

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
            locked = _lock(metering)
            if locked.status not in ASSIGNABLE_STATUSES:
                raise ServiceError("Ijrochilar «O'lchov bajarildi»dan keyin tayinlanadi")
            design = Design.objects.filter(metering=locked).first()
            price = Price.objects.filter(metering=locked).first()
            # Every refusal before any write.
            if designer is not None and design is not None and design.done:
                raise ServiceError("Dizayn allaqachon bajarilgan — qayta tayinlab bo'lmaydi")
            if pricer is not None and price is not None and price.done:
                raise ServiceError("Narx allaqachon hisoblangan — qayta tayinlab bo'lmaydi")

            if designer is not None:
                if design is None:
                    # post_save notifies the designer once this commits.
                    Design.objects.create(metering=locked, user=designer)
                    result["design"] = "created"
                elif design.user_id != designer.pk:
                    design.user = designer
                    design.save(update_fields=["user"])
                    notify_design_task(design)  # deferred to on_commit
                    result["design"] = "reassigned"
            if pricer is not None:
                if price is None:
                    Price.objects.create(metering=locked, user=pricer)
                    result["price"] = "created"
                elif price.user_id != pricer.pk:
                    price.user = pricer
                    price.save(update_fields=["user"])
                    notify_price_task(price)
                    result["price"] = "reassigned"
    except IntegrityError:
        raise ServiceError("Vazifalar hozir tayinlanmoqda — sahifani yangilang")
    return result
