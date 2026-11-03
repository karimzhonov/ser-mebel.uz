"""Selectors for the Call-center kanban on the admin dashboard."""

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from core.exceptions import ServiceConflict, ServiceError, ServiceForbidden
from core.geo import UNSET
from core.kanban import DANGER, IDLE, INFO, OK, PRIMARY, WARN, Column, build_board

from .constants import ACTIVE_SOLUTIONS, LeadSource, NoteKind, SolutionChoice

log = logging.getLogger("call_center")

# Lock order (deadlock rule): Invoice row FIRST, then its InvoiceTask rows. Every
# transaction that locks/updates tasks of a lead (complete_task, update_lead, the
# closing answer in _apply_solution) takes the invoice lock before touching tasks.
# reschedule_task / due_task_reminders lock tasks only and never lock an invoice after.


def call_center_board(to_card=None) -> list[dict]:
    """Columns for the "Call-center" kanban.

    One column per SolutionChoice, plus Янги for invoices nobody has answered yet
    (`solution` defaults to NULL). The four dead-end answers start collapsed.
    """
    from .models import Invoice

    changelist = reverse("admin:call_center_invoice_changelist")

    def by_solution(solution):
        return f"{changelist}?solution={solution.value}"

    columns = [
        Column(
            "new",
            "Янги",
            "fiber_new",
            PRIMARY,
            Q(solution__isnull=True),
            more_url=f"{changelist}?solution__isnull=True",
        ),
        Column(
            "re_phone",
            SolutionChoice.re_phone.label,
            "warning",
            WARN,
            Q(solution=SolutionChoice.re_phone),
            more_url=by_solution(SolutionChoice.re_phone),
        ),
        Column(
            "given_info",
            SolutionChoice.given_info.label,
            "info",
            INFO,
            Q(solution=SolutionChoice.given_info),
            more_url=by_solution(SolutionChoice.given_info),
        ),
        Column(
            "given_location",
            SolutionChoice.given_location.label,
            "pin_drop",
            INFO,
            Q(solution=SolutionChoice.given_location),
            more_url=by_solution(SolutionChoice.given_location),
        ),
        Column(
            "go_for_measured",
            SolutionChoice.go_for_measured.label,
            "check",
            OK,
            Q(solution=SolutionChoice.go_for_measured),
            more_url=by_solution(SolutionChoice.go_for_measured),
        ),
        Column(
            "sold_out",
            SolutionChoice.sold_out.label,
            "done_all",
            OK,
            Q(solution=SolutionChoice.sold_out),
            collapsed=True,
            more_url=by_solution(SolutionChoice.sold_out),
        ),
        Column(
            "price_problem",
            SolutionChoice.price_problem.label,
            "close",
            DANGER,
            Q(solution=SolutionChoice.price_problem),
            collapsed=True,
            more_url=by_solution(SolutionChoice.price_problem),
        ),
        Column(
            "dont_need",
            SolutionChoice.dont_need.label,
            "close",
            DANGER,
            Q(solution=SolutionChoice.dont_need),
            collapsed=True,
            more_url=by_solution(SolutionChoice.dont_need),
        ),
        Column(
            "declined",
            SolutionChoice.declined.label,
            "close",
            DANGER,
            Q(solution=SolutionChoice.declined),
            collapsed=True,
            more_url=by_solution(SolutionChoice.declined),
        ),
    ]

    queryset = Invoice.objects.select_related("client").order_by("-create_date")

    return build_board(queryset, columns, to_card or _invoice_card)


def _invoice_card(invoice) -> dict:
    return {
        "url": reverse("admin:call_center_invoice_change", args=[invoice.pk]),
        "number": invoice.pk,
        "client": str(invoice.client),
        "phone": str(invoice.client.phone),
        "desc": (invoice.desc or "").strip(),
        "when": invoice.create_date,
    }


# --- Write services (used by the REST API; mirror InvoiceAdmin / InvoiceActions) ---

# Answers after which the invoice is closed for editing (InvoiceAdmin.has_change_permission).
CLOSED_SOLUTIONS = [
    SolutionChoice.sold_out,
    SolutionChoice.go_for_measured,
    SolutionChoice.price_problem,
    SolutionChoice.dont_need,
    SolutionChoice.declined,
]
# Answers after which the client has been served and no other answer is accepted
# (InvoiceActions.get_unfold_action).
SERVED_SOLUTIONS = [SolutionChoice.sold_out, SolutionChoice.go_for_measured]

# Answers that end the sales conversation: open reminders of the lead are closed with them.
CLOSING_SOLUTIONS = (
    SolutionChoice.price_problem,
    SolutionChoice.dont_need,
    SolutionChoice.declined,
)

# "Which stage does the lead go to?" when a task is completed (keys = lead_board columns).
KEEP = "keep"
OUTCOME_SOLUTION = {
    "re_phone": SolutionChoice.re_phone,
    "given_info": SolutionChoice.given_info,
    "given_location": SolutionChoice.given_location,
    "price_problem": SolutionChoice.price_problem,
    "dont_need": SolutionChoice.dont_need,
    "declined": SolutionChoice.declined,
}
OUTCOME_KEYS = (*OUTCOME_SOLUTION, "go_for_measured", KEEP)

DEFAULT_TASK_TEXT = "Mijozga qo'ng'iroq qilish"
TOMORROW_HOUR = 10
TODAY_EVENING_HOUR = 18


def with_task_annotations(qs):
    """Annotate invoices with next_due / next_task_id / next_task_text / open_tasks
    (what InvoiceSerializer reads without a query per row)."""
    from django.db.models import Count, IntegerField, OuterRef, Subquery, Value
    from django.db.models.functions import Coalesce

    from .models import InvoiceTask

    open_tasks = InvoiceTask.objects.filter(invoice=OuterRef("pk"), done_at__isnull=True)
    first_open = open_tasks.order_by("due_at", "pk")
    return qs.annotate(
        next_due=Subquery(first_open.values("due_at")[:1]),
        next_task_id=Subquery(first_open.values("pk")[:1]),
        next_task_text=Subquery(first_open.values("text")[:1]),
        open_tasks=Coalesce(
            Subquery(
                open_tasks.order_by().values("invoice").annotate(c=Count("pk")).values("c")[:1],
                output_field=IntegerField(),
            ),
            Value(0),
        ),
    )


def invoice_is_editable(invoice) -> bool:
    return invoice.solution not in CLOSED_SOLUTIONS


# ------------------------------------------------------------------ people
def eligible_assignees():
    """Panel users who can work a lead: may change invoices and can log in."""
    from oauth.services import users_with_perm

    return users_with_perm("call_center", "change_invoice").filter(is_staff=True)


def _require_eligible(user):
    if user is None or not eligible_assignees().filter(pk=user.pk).exists():
        raise ServiceError("Bu xodimga ariza biriktirib bo'lmaydi")


def _user_name(user) -> str:
    return (user.name or str(user.phone)) if user else ""


# ------------------------------------------------------------------ notes / history
def _log(invoice, kind, author, *, text="", meta=None, task=None):
    from .models import InvoiceNote

    return InvoiceNote.objects.create(
        invoice=invoice, author=author, kind=kind, text=text, meta=meta or {}, task=task
    )


def add_note(invoice, *, author, text, kind=NoteKind.note, meta=None, task=None):
    """Append a note to the lead's history. A plain note also becomes `Invoice.desc`
    (the cache the board card, the search and the legacy admin read)."""
    text = (text or "").strip()
    if not text:
        raise ServiceError("Izoh bo'sh")
    with transaction.atomic():
        note = _log(invoice, kind, author, text=text, meta=meta, task=task)
        if kind == NoteKind.note:
            invoice.desc = text
            invoice.save(update_fields=["desc", "update_date"])
    return note


def log_solution(invoice, old, new, author=None, extra=None):
    """History line for an answer change (also called by metering/order creation).
    `extra` is merged into the line's meta (e.g. {"closed_tasks": 2})."""
    if old == new:
        return None
    return _log(invoice, NoteKind.solution, author, meta={"from": old, "to": new, **(extra or {})})


def create_invoice(
    *,
    fio: str,
    phone,
    desc: str | None = None,
    source: str | None = None,
    author=None,
    assigned_to=None,
    task: dict | None = None,
    lat=None,
    lon=None,
    address: str = "",
    address_link: str | None = None,
    via: str = "panel",
):
    """A new lead. The client is looked up by phone and created if new (an existing
    client's name is never overwritten). `assigned_to` defaults to the author;
    `task` = {text, due_at} adds the first reminder. `lat`/`lon` (+ `address`,
    `address_link`) attach the client's location."""
    from client.models import Client
    from core.geo import make_point

    from .models import Invoice

    if source and source not in LeadSource.values:
        raise ServiceError("Manba noto'g'ri")
    if assigned_to is not None and (author is None or assigned_to.pk != author.pk):
        _require_eligible(assigned_to)
    assignee = assigned_to or author
    point = None
    if lat is not None or lon is not None:
        point = make_point(lat, lon)
        if point is None:
            raise ServiceError("Lokatsiya koordinatalari noto'g'ri")
    with transaction.atomic():
        client, _ = Client.objects.get_or_create(phone=phone, defaults={"fio": fio})
        invoice = Invoice.objects.create(
            client=client,
            source=source or None,
            assigned_to=assignee,
            created_by=author,
            lat=point.lat if point else None,
            lon=point.lon if point else None,
            address=(address or "").strip()[:255],
            address_link=address_link or None,
        )
        if point or address_link:
            _log(invoice, NoteKind.location, author, meta=_location_meta(point, via, address_link))
        if desc and desc.strip():
            add_note(invoice, author=author, text=desc)
        if task:
            create_task(
                invoice,
                text=task.get("text"),
                due_at=task["due_at"],
                by=author,
                assigned_to=assignee,
                check=False,
            )
    return invoice


def _close_open_tasks(invoice, by, now) -> int:
    """Mark every still-open reminder of the lead done (the lead is closed: no more calls)."""
    return invoice.tasks.filter(done_at__isnull=True).update(done_at=now, done_by=by)


def _apply_solution(invoice, solution, author) -> int:
    """Write the new answer + its history line (caller holds the lead lock, in a
    transaction). A closing answer also closes the lead's open tasks and records how
    many in the history line. Returns the number of tasks closed."""
    old = invoice.solution
    invoice.solution = solution
    invoice.save()
    closed = 0
    if old != int(solution) and solution in CLOSING_SOLUTIONS:
        closed = _close_open_tasks(invoice, author, _now())
    log_solution(invoice, old, int(solution), author, {"closed_tasks": closed} if closed else None)
    return closed


def set_invoice_solution(invoice, solution: int, *, author=None):
    """Record the call-centre answer for an invoice.

    "Замерга борилади" is not accepted here: it is set by creating the metering
    (metering.services.create_metering), exactly as the admin button redirects to the
    metering form. "Сотилди" is set only by creating an order.
    """
    solution = SolutionChoice(solution)
    if solution == SolutionChoice.go_for_measured:
        raise ServiceError("O'lchov yarating — javob kodi avtomatik o'zgaradi")
    if solution == SolutionChoice.sold_out:
        raise ServiceError("«Sotildi» buyurtma yaratilganda avtomatik qo'yiladi")

    with transaction.atomic():
        # re-read under a lock: a concurrent metering/order may have just served it
        invoice.solution = (
            type(invoice)
            .objects.select_for_update()
            .values_list("solution", flat=True)
            .get(pk=invoice.pk)
        )
        if invoice.solution in SERVED_SOLUTIONS:
            raise ServiceError(f"Mijozga ({invoice.client.fio}) xizmat ko'rsatilgan")
        _apply_solution(invoice, solution, author)
    return invoice


def update_lead(invoice, *, by, assigned_to=UNSET, source=UNSET):
    """Reassign the lead / fix its source. Allowed on closed leads too."""
    with transaction.atomic():
        # canonical order: invoice lock before the tasks are updated below
        type(invoice).objects.select_for_update(of=("self",)).get(pk=invoice.pk)
        if assigned_to is not UNSET and (assigned_to.pk if assigned_to else None) != (
            invoice.assigned_to_id
        ):
            if assigned_to is not None:
                _require_eligible(assigned_to)
            previous_id = invoice.assigned_to_id
            moved = 0
            if assigned_to is not None and previous_id is not None:
                # the previous owner's open reminders follow the lead
                moved = invoice.tasks.filter(
                    assigned_to_id=previous_id, done_at__isnull=True
                ).update(assigned_to=assigned_to)
            invoice.assigned_to = assigned_to
            meta = {
                "to_id": assigned_to.pk if assigned_to else None,
                "to_name": _user_name(assigned_to) or None,
            }
            if moved:
                meta["moved_tasks"] = moved
            _log(invoice, NoteKind.assigned, by, meta=meta)
        if source is not UNSET and (source or None) != invoice.source:
            if source and source not in LeadSource.values:
                raise ServiceError("Manba noto'g'ri")
            _log(invoice, NoteKind.source, by, meta={"from": invoice.source, "to": source or None})
            invoice.source = source or None
        invoice.save()
    return invoice


# ------------------------------------------------------------------ location
def _location_meta(point, via, link=None) -> dict:
    return {
        "lat": point.lat_str if point else None,
        "lon": point.lon_str if point else None,
        "link": bool(link),  # a short link may locate the lead without a point
        "via": via,
    }


def _fill_down(invoice, by=None) -> list[tuple[str, int]]:
    """Give the lead's metering - and that metering's order - the lead's location where
    they have none of their own. Archived meterings are filled too (blank-only)."""
    from core.geo import copy_location
    from metering.models import Metering
    from order.models import Order

    filled: list[tuple[str, int]] = []
    metering = Metering.objects.select_for_update().filter(invoice=invoice).first()
    if metering is None:
        return filled
    fields = copy_location(invoice, metering)
    if fields:
        metering._history_user = by  # not the request's user: it may be the bot principal
        metering.save(update_fields=fields)
        filled.append(("metering", metering.pk))
    order = Order.objects.select_for_update().filter(metering=metering).first()
    if order is not None:
        fields = copy_location(metering, order)
        if fields:
            order._history_user = by
            order.save(update_fields=fields)
            filled.append(("order", order.pk))
    return filled


def set_invoice_location(invoice, *, point, link=UNSET, address=UNSET, by, via="panel"):
    """Attach (or, with `point=None` and no link, clear) the lead's map location.

    Returns (invoice, changed, filled): `filled` = [("metering"|"order", id)] that
    inherited it. The same point again is a no-op (no history line). A blank address
    never overwrites a typed one; from the bot (`via="bot"`, a venue's address) it only
    fills a blank. Allowed on closed leads."""
    from core.geo import resolve_location

    from .models import Invoice

    with transaction.atomic():
        locked = Invoice.objects.select_for_update().get(pk=invoice.pk)
        new_lat, new_lon, new_link = resolve_location(locked, point, link)
        moved = locked.lat != new_lat or locked.lon != new_lon or locked.address_link != new_link
        fields = []
        if moved:
            locked.lat, locked.lon, locked.address_link = new_lat, new_lon, new_link
            fields += ["lat", "lon", "address_link"]
        if address is not UNSET:
            text = (address or "").strip()[:255]
            if via == "bot":  # a venue's address only fills a blank one
                write = bool(text) and not locked.address
            else:  # the panel may also clear it, while a point still locates the lead
                write = bool(text or locked.lat is not None) and text != locked.address
            if write and text != locked.address:
                locked.address = text
                fields.append("address")
        changed = bool(fields)
        filled: list[tuple[str, int]] = []
        if changed:
            locked.save(update_fields=fields + ["update_date"])
            if moved:
                _log(
                    locked,
                    NoteKind.location,
                    by,
                    meta=_location_meta(point if moved else None, via, locked.address_link),
                )
        if locked.lat is not None or locked.address_link:
            filled = _fill_down(locked, by)
    for name in ("lat", "lon", "address", "address_link", "update_date"):
        setattr(invoice, name, getattr(locked, name))
    return invoice, changed, filled


def location_candidates(user, *, phone=None, limit=8) -> list[tuple[str, object]]:
    """Where the bot may attach a received location: [("invoice"|"metering", obj)].

    No phone: the user's own "location requested" leads, then open meterings (those
    without a point first). With a phone: that client's open leads and editable
    meterings. Each kind needs view + change permission."""
    from django.db.models import F

    from metering.constants import MeteringStatus
    from metering.models import Metering

    from .models import Invoice

    can_inv = user.has_perm("call_center.view_invoice") and user.has_perm(
        "call_center.change_invoice"
    )
    can_met = user.has_perm("metering.view_metering") and user.has_perm("metering.change_metering")
    out: list[tuple[str, object]] = []
    if phone is not None:
        if can_inv:
            qs = (
                Invoice.objects.filter(client_id=phone)
                .exclude(solution__in=[int(x) for x in CLOSED_SOLUTIONS])
                .select_related("client", "assigned_to")
                .order_by("-create_date")
            )
            out += [("invoice", i) for i in qs[:limit]]
        if can_met:
            qs = (
                Metering.objects.filter(client_id=phone)
                .exclude(status__in=MeteringStatus.archive_statuses())
                .select_related("client", "invoice")
                .order_by(F("date_time").desc(nulls_last=True))
            )
            out += [("metering", m) for m in qs[:limit]]
        return out[:limit]
    if can_inv:
        qs = (
            Invoice.objects.filter(assigned_to=user, solution=SolutionChoice.given_location)
            .select_related("client", "assigned_to")
            .order_by("-create_date")
        )
        out += [("invoice", i) for i in qs[:5]]
    if can_met:
        from django.db.models import BooleanField, ExpressionWrapper

        qs = (
            Metering.objects.filter(status__in=[MeteringStatus.created, MeteringStatus.other_day])
            .select_related("client", "invoice")
            .annotate(_no_point=ExpressionWrapper(Q(lat__isnull=True), output_field=BooleanField()))
            .order_by("-_no_point", F("date_time").asc(nulls_last=True), "pk")
        )
        out += [("metering", m) for m in qs[: max(limit - len(out), 0)]]
    return out[:limit]


# ------------------------------------------------------------------ tasks
def create_task(invoice, *, text, due_at, by, assigned_to=None, check=True):
    from .models import InvoiceTask

    if assigned_to is not None:
        assignee = assigned_to
    else:
        assignee = invoice.assigned_to
        if assignee is not None and assignee != by and check:
            try:
                _require_eligible(assignee)
            except ServiceError:
                assignee = by  # the lead's owner can no longer take work: fall back to `by`
        assignee = assignee or by
    if assignee is None:
        raise ServiceError("Mas'ul xodim ko'rsatilmagan")
    if check and assigned_to is not None and assignee != by:
        _require_eligible(assignee)
    if not due_at:
        raise ServiceError("Vaqtni ko'rsating")
    with transaction.atomic():
        return InvoiceTask.objects.create(
            invoice=invoice,
            text=(text or "").strip()[:500] or DEFAULT_TASK_TEXT,
            due_at=due_at,
            assigned_to=assignee,
            created_by=by,
        )


def can_manage_task(user, task) -> bool:
    return bool(
        user
        and (
            user.is_superuser
            or task.assigned_to_id == user.pk
            or task.created_by_id == user.pk
            or user.has_perm("call_center.manage_invoice")
        )
    )


def _locked_open_task(task, by):
    """Re-read `task` under a row lock; refuse when done / not the user's to touch."""
    from .models import InvoiceTask

    fresh = InvoiceTask.objects.select_for_update().get(pk=task.pk)
    if fresh.done_at is not None:
        raise ServiceConflict("Allaqachon bajarilgan")
    if not can_manage_task(by, fresh):
        raise ServiceForbidden("Bu vazifa sizniki emas")
    return fresh


def task_outcomes(invoice, user) -> list[str]:
    """Stages the lead may go to when `user` completes one of its tasks. ["keep"] =
    no choice (closed lead, or the user may not move leads); otherwise the stage is
    required. Staying on the current stage means picking it (`keep` is not offered)."""
    if invoice.solution in CLOSED_SOLUTIONS or not user.has_perm("call_center.change_invoice"):
        return [KEEP]
    out = ["re_phone", "given_info", "given_location"]
    if user.has_perm("metering.add_metering"):
        out.append("go_for_measured")
    return [*out, "price_problem", "dont_need", "declined"]


def _next_due(next_task, now) -> tuple[datetime, str | None]:
    """{preset} or {due_at, text?} (exactly one of preset/due_at) -> (due, text)."""
    bad = "Qayta qo'ng'iroq vaqti noto'g'ri"
    if not isinstance(next_task, dict):
        raise ServiceError(bad, "next_task")
    preset, due_at = next_task.get("preset"), next_task.get("due_at")
    if bool(preset) == bool(due_at):
        raise ServiceError(bad, "next_task")
    text = next_task.get("text")
    if text is not None and not isinstance(text, str):
        raise ServiceError(bad, "next_task")
    if preset:
        try:
            return due_preset(preset, now), text
        except ServiceError:
            raise ServiceError(bad, "next_task")
    if not isinstance(due_at, datetime):
        raise ServiceError(bad, "next_task")
    if due_at.tzinfo is not None:  # USE_TZ is off: store naive local time
        due_at = timezone.make_naive(due_at)
    if due_at <= now:
        raise ServiceError("O'tgan vaqt — kelajakdagi vaqtni kiriting", "next_task")
    return due_at, text


@dataclass
class TaskCompletion:
    task: object
    invoice: object
    next_task: object = None
    closed_tasks: int = 0


def complete_task(task, *, by, note="", outcome=None, next_task=None) -> TaskCompletion:
    """Finish a task and move its lead to the stage the user chose (`outcome`, see
    task_outcomes). re_phone requires `next_task` (the next call); given_info /
    given_location accept one; closing answers and `keep` refuse one. A closing
    answer closes the lead's other open tasks."""
    from .models import Invoice

    with transaction.atomic():
        # canonical order: invoice first, then the task (see top of module)
        invoice = (
            Invoice.objects.select_for_update(of=("self",))
            .select_related("client", "assigned_to")
            .get(pk=task.invoice_id)
        )
        task = _locked_open_task(task, by)
        allowed = task_outcomes(invoice, by)
        if outcome == "go_for_measured":
            raise ServiceError("O'lchov yarating — javob kodi avtomatik o'zgaradi", "outcome")
        if outcome is None and allowed == [KEEP]:
            outcome = KEEP
        if outcome is None:
            raise ServiceError("Keyingi bosqichni tanlang", "outcome")
        if outcome not in allowed:
            raise ServiceError("Bu bosqichni tanlab bo'lmaydi", "outcome")
        now = _now()
        due = text = None
        if outcome == "re_phone" and next_task is None:
            raise ServiceError("Qayta qo'ng'iroq vaqtini ko'rsating", "next_task")
        if next_task is not None:
            if outcome in ("re_phone", "given_info", "given_location"):
                due, text = _next_due(next_task, now)
            else:
                raise ServiceError("Yopilgan arizaga vazifa qo'shib bo'lmaydi", "next_task")

        task.done_at = now
        task.done_by = by
        task.save(update_fields=["done_at", "done_by"])
        if (note or "").strip():
            add_note(invoice, author=by, text=note, task=task)
        closed = 0
        if outcome in OUTCOME_SOLUTION:
            closed = _apply_solution(invoice, OUTCOME_SOLUTION[outcome], by)
        created = None
        if due is not None:
            created = create_task(invoice, text=text, due_at=due, by=by, assigned_to=None)
    task.invoice = invoice
    return TaskCompletion(task=task, invoice=invoice, next_task=created, closed_tasks=closed)


def reschedule_task(task, *, by, due_at):
    if not due_at:
        raise ServiceError("Vaqtni ko'rsating")
    with transaction.atomic():
        task = _locked_open_task(task, by)
        task.due_at = due_at
        task.notified_at = None
        task.remind_seq += 1
        task.save(update_fields=["due_at", "notified_at", "remind_seq"])
    return task


def snooze_task(task, *, by, preset):
    if preset not in ("1h", "tomorrow"):
        raise ServiceError("Noma'lum vaqt tanlovi")
    return reschedule_task(task, by=by, due_at=due_preset(preset, _now()))


# ------------------------------------------------------------------ time helpers
def _now() -> datetime:
    # USE_TZ=False, TIME_ZONE=Asia/Tashkent: naive local time
    return datetime.now()


def due_preset(preset, now) -> datetime:
    """1h = in an hour; today = 18:00 today (an hour from now after 17:00);
    tomorrow = 10:00 tomorrow."""
    if preset == "1h":
        return (now + timedelta(hours=1)).replace(second=0, microsecond=0)
    if preset == "today":
        if now.hour < 17:
            return now.replace(hour=TODAY_EVENING_HOUR, minute=0, second=0, microsecond=0)
        return (now + timedelta(hours=1)).replace(second=0, microsecond=0)
    if preset == "tomorrow":
        return (now + timedelta(days=1)).replace(
            hour=TOMORROW_HOUR, minute=0, second=0, microsecond=0
        )
    raise ServiceError("Noma'lum vaqt tanlovi")


_TIME_ONLY = re.compile(r"^(\d{1,2}):(\d{2})$")
_DATE = re.compile(r"^(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?(?:\s+(\d{1,2}):(\d{2}))?$")
_BAD_TIME = "Vaqtni tushunmadim. Masalan: 14:30, 25.12 yoki 25.12 14:30"


def parse_due(text, now) -> datetime:
    """ "HH:MM" (today), "dd.mm", "dd.mm HH:MM", "dd.mm.yyyy HH:MM". A date without a
    time means 10:00. A moment in the past is refused."""
    raw = (text or "").strip()
    try:
        m = _TIME_ONLY.match(raw)
        if m:
            due = now.replace(hour=int(m[1]), minute=int(m[2]), second=0, microsecond=0)
        else:
            m = _DATE.match(raw)
            if not m:
                raise ValueError
            hour, minute = (int(m[4]), int(m[5])) if m[4] is not None else (TOMORROW_HOUR, 0)
            due = datetime(int(m[3] or now.year), int(m[2]), int(m[1]), hour, minute)
    except ValueError:
        raise ServiceError(_BAD_TIME)
    if due <= now:
        raise ServiceError("O'tgan vaqt — kelajakdagi vaqtni kiriting")
    return due


# ------------------------------------------------------------------ board / timeline / agenda
def lead_board(qs, *, limit_active=100, limit_closed=20) -> list[dict]:
    """Columns of the SPA's lead board over `qs`; each card is an Invoice (the API
    serialises them). Dragging is allowed into `droppable` columns only."""
    S = SolutionChoice
    # (key, solution, accent, droppable, collapsed)
    spec = [
        ("new", None, PRIMARY, False, False),
        ("re_phone", S.re_phone, WARN, True, False),
        ("given_info", S.given_info, INFO, True, False),
        ("given_location", S.given_location, INFO, True, False),
        ("go_for_measured", S.go_for_measured, OK, True, False),
        ("sold_out", S.sold_out, OK, False, False),
        ("price_problem", S.price_problem, DANGER, True, True),
        ("dont_need", S.dont_need, DANGER, True, True),
        ("declined", S.declined, DANGER, True, True),
    ]
    from core.i18n import BOARD_COLUMN

    titles = BOARD_COLUMN["callcenter"]
    columns, meta = [], {}
    for key, solution, accent, droppable, collapsed in spec:
        flt = Q(solution__isnull=True) if solution is None else Q(solution=solution)
        columns.append(Column(key, titles.get(key, key), "", accent or IDLE, flt, collapsed))
        meta[key] = (None if solution is None else int(solution), droppable)
    board = build_board(
        qs,
        columns,
        lambda invoice: invoice,
        limit=lambda c: (
            limit_closed
            if c.key in ("price_problem", "dont_need", "declined", "sold_out")
            else limit_active
        ),
    )
    return [
        {
            "key": c["key"],
            "title": c["title"],
            "tone": c["accent"],
            "solution": meta[c["key"]][0],
            "droppable": meta[c["key"]][1],
            "collapsed": c["collapsed"],
            "count": c["count"],
            "cards": c["cards"],
        }
        for c in board
    ]


def lead_timeline(invoice) -> list[dict]:
    """Everything that happened to the lead, newest first."""
    from core.i18n import metering_status
    from metering.models import Metering
    from order.models import Order

    from .dto import task_dto, user_ref

    entries = []

    def add(at, type_, author=None, kind=None, text="", meta=None, task=None, link=None):
        entries.append(
            {
                "type": type_,
                "at": at,
                "author": user_ref(author) if author else None,
                "kind": kind,
                "text": text,
                "meta": meta or {},
                "task": task_dto(task) if task else None,
                "link": link,
            }
        )

    task_notes = {}
    for note in invoice.notes.select_related("author"):
        if note.task_id and note.kind == NoteKind.note:
            task_notes[note.task_id] = note
            continue
        add(note.created_at, "note", note.author, note.kind, note.text, note.meta)
    for task in invoice.tasks.select_related("assigned_to", "created_by", "done_by"):
        add(task.created_at, "task_created", task.created_by, text=task.text, task=task)
        if task.done_at:
            note = task_notes.get(task.pk)
            add(task.done_at, "task_done", task.done_by, text=note.text if note else "", task=task)
    for task_id, note in task_notes.items():
        # a note written when a task was closed is shown on the "done" line only when
        # that line exists (the task may have been deleted)
        if not any(e["task"] and e["task"]["id"] == task_id for e in entries):
            add(note.created_at, "note", note.author, note.kind, note.text, note.meta)
    metering = Metering.objects.filter(invoice=invoice).first()
    if metering:
        add(
            metering.create_date,
            "metering",
            text=metering_status(metering.status),
            link={"kind": "metering", "id": metering.pk},
        )
        order = Order.objects.filter(metering=metering).first()
        if order:
            add(
                datetime.combine(order.reception_date, datetime.min.time()),
                "order",
                text=f"#{order.order_number}",
                link={"kind": "order", "id": order.pk},
            )
    add(invoice.create_date, "created", invoice.created_by)
    entries.sort(key=lambda e: e["at"], reverse=True)
    return entries


def task_agenda(*, assignee, now) -> dict:
    """Open tasks of one person: overdue (before now), today (rest of the day), upcoming."""
    from .models import InvoiceTask

    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    base = InvoiceTask.objects.filter(assigned_to=assignee, done_at__isnull=True).select_related(
        "invoice__client", "invoice__assigned_to", "assigned_to", "created_by"
    )
    return {
        "overdue": list(base.filter(due_at__lt=now).order_by("due_at")[:500]),
        "today": list(base.filter(due_at__gte=now, due_at__lt=tomorrow).order_by("due_at")),
        "upcoming": list(base.filter(due_at__gte=tomorrow).order_by("due_at")[:100]),
    }


def task_counts(*, assignee, now) -> dict:
    from .models import InvoiceTask

    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    base = InvoiceTask.objects.filter(assigned_to=assignee, done_at__isnull=True)
    return {
        "overdue": base.filter(due_at__lt=now).count(),
        "today": base.filter(due_at__gte=now, due_at__lt=tomorrow).count(),
    }


def due_task_reminders(now) -> int:
    """Send the bot reminder of every task that came due (once per task + due time)."""
    from accounting.services import once

    from . import events
    from .models import InvoiceTask

    sent = 0
    due = (
        InvoiceTask.objects.filter(done_at__isnull=True, notified_at__isnull=True, due_at__lte=now)
        .select_related("invoice__client", "invoice__assigned_to", "assigned_to", "created_by")
        .order_by("due_at")[:200]
    )
    for task in due:
        with transaction.atomic():
            marked = InvoiceTask.objects.filter(
                pk=task.pk, due_at=task.due_at, done_at__isnull=True, notified_at__isnull=True
            ).update(notified_at=now)
            if not marked:
                continue  # done / moved / taken by another worker meanwhile
            if not once(f"cc:task:{task.pk}:{task.remind_seq}"):
                continue
            user = task.assigned_to
            if user.is_active and user.telegram_id:
                events.task_due(task)
                sent += 1
            else:
                log.info("task %s: %s has no Telegram, reminder skipped", task.pk, user.pk)
    return sent


# ------------------------------------------------------------------ bot helpers
def lookup_client(phone):
    """(client|None, number of leads, the newest still-open lead|None) for the bot."""
    from client.models import Client

    from .models import Invoice

    client = Client.objects.filter(pk=phone).first()
    if client is None:
        return None, 0, None
    invoices = Invoice.objects.filter(client=client).select_related("client", "assigned_to")
    open_invoice = (
        invoices.exclude(solution__in=[int(s) for s in CLOSED_SOLUTIONS])
        .order_by("-create_date")
        .first()
    )
    return client, invoices.count(), open_invoice


def needs_task(invoice, open_tasks: int) -> bool:
    return invoice.solution in ACTIVE_SOLUTIONS and open_tasks == 0
