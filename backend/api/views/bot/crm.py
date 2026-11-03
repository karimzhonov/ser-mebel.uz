"""Bot API - CRM: a salesperson adds a lead from Telegram and answers task reminders.

The actor is the panel user linked to the Telegram account (oauth.User.telegram_id);
call_center.services decides, the bot only relays.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from phonenumber_field.phonenumber import PhoneNumber
from phonenumbers import NumberParseException
from rest_framework.exceptions import NotFound, ParseError, PermissionDenied
from rest_framework.response import Response

from call_center import dto
from call_center import events as E
from call_center import services as S
from call_center.constants import LeadSource
from call_center.models import Invoice, InvoiceTask
from core.exceptions import ServiceConflict, ServiceError, ServiceForbidden
from core.geo import UNSET, make_point, obj_map_url
from metering.models import Metering
from metering.services import set_metering_location

from .base import BotAPIView

DUPLICATE_WINDOW_MIN = 10
REMIND_PRESETS = ("today", "tomorrow", "none")


def _bad(detail: str, field: str | None = None) -> Response:
    body = {"detail": detail}
    if field:
        body["field"] = field
    return Response(body, status=400)


def _phone(raw) -> PhoneNumber | None:
    try:
        phone = PhoneNumber.from_string(str(raw or ""), region="UZ")
    except NumberParseException:
        return None
    return phone if phone.is_valid() else None


def _dict_body(request) -> dict:
    if not isinstance(request.data, dict):
        raise ParseError("So'rov noto'g'ri.")
    return request.data


class ClientLookupView(BotAPIView):
    """GET ?phone= -> {exists, fio, invoices_count, open_invoice: LeadBrief|null}."""

    def get(self, request):
        self.require_site_perm("call_center.view_invoice")
        phone = _phone(request.query_params.get("phone"))
        if phone is None:
            return _bad("Telefon raqami noto'g'ri", "phone")
        client, count, open_invoice = S.lookup_client(phone)
        return Response(
            {
                "exists": client is not None,
                "fio": client.fio if client else None,
                "invoices_count": count,
                "open_invoice": dto.lead_brief(open_invoice) if open_invoice else None,
            }
        )


def _location_perms(user) -> tuple[bool, bool]:
    inv = user.has_perm("call_center.view_invoice") and user.has_perm("call_center.change_invoice")
    met = user.has_perm("metering.view_metering") and user.has_perm("metering.change_metering")
    return inv, met


def _point_from(raw):
    """{lat, lon} (numbers or strings) -> MapPoint; None when the pair is not valid."""
    if not isinstance(raw, dict):
        return None
    return make_point(raw.get("lat"), raw.get("lon"))


class LocationCandidatesView(BotAPIView):
    """GET [?phone=] -> {items: [LocationTarget], can_new_lead}."""

    def get(self, request):
        user = self.require_linked_user()
        inv, met = _location_perms(user)
        if not (inv or met):
            raise PermissionDenied("Bu amal uchun huquq yetarli emas.")
        raw = request.query_params.get("phone")
        phone = None
        if raw not in (None, ""):
            phone = _phone(raw)
            if phone is None:
                return _bad("Telefon raqami noto'g'ri", "phone")
        items = S.location_candidates(user, phone=phone)
        return Response(
            {
                "items": [dto.location_target(kind, obj, user) for kind, obj in items],
                "can_new_lead": user.has_perm("call_center.add_invoice")
                and user.has_perm("call_center.view_invoice"),
            }
        )


class LocationSetView(BotAPIView):
    """POST {target: {kind, id}, lat, lon, address?, live?} ->
    {target, changed, filled: [{kind, id}], map_url, url}."""

    def post(self, request):
        user = self.require_linked_user()
        data = _dict_body(request)
        target = data.get("target")
        if not isinstance(target, dict) or target.get("kind") not in ("invoice", "metering"):
            return _bad("Nishon noto'g'ri", "target")
        kind = target["kind"]
        try:
            pk = int(target.get("id"))
        except (TypeError, ValueError):
            return _bad("Nishon noto'g'ri", "target")
        inv, met = _location_perms(user)
        if not (inv if kind == "invoice" else met):
            raise PermissionDenied("Bu amal uchun huquq yetarli emas.")
        point = make_point(data.get("lat"), data.get("lon"))
        if point is None:
            return _bad("Koordinatalar noto'g'ri", "location")
        address = str(data.get("address") or "").strip()
        kwargs = {"address": address} if address else {}
        if kind == "invoice":
            obj = Invoice.objects.select_related("client", "assigned_to").filter(pk=pk).first()
            if obj is None:
                raise NotFound()
            _, changed, filled = S.set_invoice_location(
                obj, point=point, by=user, via="bot", **kwargs
            )
            url = E.lead_url(obj.pk)
        else:
            obj = Metering.objects.select_related("client", "invoice").filter(pk=pk).first()
            if obj is None:
                raise NotFound()
            if obj.address:  # a venue's address only fills a blank one
                kwargs = {}
            _, changed, filled = set_metering_location(obj, point=point, by=user, **kwargs)
            url = E.metering_url(obj.pk)
        return Response(
            {
                "target": dto.location_target(kind, obj, user),
                "changed": changed,
                "filled": [{"kind": k, "id": i} for k, i in filled],
                "map_url": obj_map_url(obj),
                "url": url,
            }
        )


class DueParseView(BotAPIView):
    """POST {text} -> {due_at} (add_invoice or view_invoice); 400 {detail, field: "remind"} when it can't be read."""

    def post(self, request):
        user = self.require_linked_user()
        if not (
            user.has_perm("call_center.add_invoice") or user.has_perm("call_center.view_invoice")
        ):
            raise PermissionDenied("Bu amal uchun huquq yetarli emas.")
        data = _dict_body(request)
        try:
            due = S.parse_due(data.get("text"), S._now())
        except ServiceError as e:
            return _bad(e.message, "remind")
        return Response({"due_at": dto.dt(due)})


class LeadCreateView(BotAPIView):
    """POST {name, phone, source, note, remind} -> 201 {invoice, task, client_existed, url}."""

    def post(self, request):
        user = self.require_site_perm("call_center.add_invoice")
        data = _dict_body(request)
        name = str(data.get("name") or "").strip()
        if not name or len(name) > 255:
            return _bad("Ismni kiriting", "name")
        phone = _phone(data.get("phone"))
        if phone is None:
            return _bad("Telefon raqami noto'g'ri", "phone")
        source = data.get("source")
        if source not in LeadSource.values:
            return _bad("Manbani tanlang", "source")
        try:
            due = self._due(data.get("remind"))
        except ServiceError as e:
            return _bad(e.message, "remind")
        loc = data.get("location")
        point, address = None, ""
        if loc not in (None, ""):
            point = _point_from(loc)
            if point is None:
                return _bad("Lokatsiya noto'g'ri", "location")
            address = str(loc.get("address") or "").strip()

        from client.models import Client

        existed = Client.objects.filter(pk=phone).exists()
        # a retried POST (lost response) must not create a second lead
        recent = (
            Invoice.objects.filter(
                client_id=phone,
                created_by=user,
                create_date__gte=datetime.now() - timedelta(minutes=DUPLICATE_WINDOW_MIN),
            )
            .select_related("client", "assigned_to")
            .order_by("-create_date")
            .first()
        )
        if recent is not None:
            if point is not None and recent.lat is None:
                # the first request lost its location (or it came on the retry): attach it
                S.set_invoice_location(
                    recent, point=point, address=address or UNSET, by=user, via="bot"
                )
            task = recent.tasks.select_related("assigned_to").order_by("pk").first()
            return Response(
                {
                    "invoice": dto.lead_brief(recent),
                    "task": dto.task_dto(task) if task else None,
                    # the first request created the client; report what it saw
                    "client_existed": recent.client.invoice_set.count() > 1,
                    "url": E.lead_url(recent.pk),
                    "duplicate": True,
                },
                status=200,
            )
        invoice = S.create_invoice(
            fio=name,
            phone=phone,
            desc=str(data.get("note") or "").strip()[:5000] or None,
            source=source,
            author=user,
            task={"text": None, "due_at": due} if due else None,
            lat=point.lat if point else None,
            lon=point.lon if point else None,
            address=address,
            via="bot",
        )
        task = invoice.tasks.select_related("assigned_to").first()
        return Response(
            {
                "invoice": dto.lead_brief(invoice),
                "task": dto.task_dto(task) if task else None,
                "client_existed": existed,
                "url": E.lead_url(invoice.pk),
            },
            status=201,
        )

    @staticmethod
    def _due(remind) -> datetime | None:
        if not remind:
            return None
        if not isinstance(remind, dict):
            raise ServiceError("Eslatma vaqti noto'g'ri")
        now = S._now()
        if "preset" in remind:
            if remind["preset"] not in REMIND_PRESETS:
                raise ServiceError("Eslatma vaqti noto'g'ri")
            return None if remind["preset"] == "none" else S.due_preset(remind["preset"], now)
        if "at" in remind:
            try:
                due = datetime.fromisoformat(str(remind["at"]))
            except ValueError:
                raise ServiceError("Eslatma vaqti noto'g'ri")
            if due <= now:
                raise ServiceError("O'tgan vaqt — kelajakdagi vaqtni kiriting")
            return due
        raise ServiceError("Eslatma vaqti noto'g'ri")


class _TaskView(BotAPIView):
    def get_task(self, pk):
        task = InvoiceTask.objects.select_related("assigned_to").filter(pk=pk).first()
        if task is None:
            raise NotFound()
        return task


class TaskDetailView(_TaskView):
    """GET -> {task, invoice: LeadBrief, outcomes, next_required, url}: what the bot
    needs to ask "which stage next?"; 409 already done, 403 not the user's task."""

    def get(self, request, pk):
        user = self.require_site_perm("call_center.view_invoice")
        task = (
            InvoiceTask.objects.select_related(
                "assigned_to", "invoice__client", "invoice__assigned_to"
            )
            .filter(pk=pk)
            .first()
        )
        if task is None:
            raise NotFound()
        if task.done_at is not None:
            raise ServiceConflict("Allaqachon bajarilgan")
        if not S.can_manage_task(user, task):
            raise ServiceForbidden("Bu vazifa sizniki emas")
        return Response(
            {
                "task": dto.task_dto(task),
                "invoice": dto.lead_brief(task.invoice),
                "outcomes": S.task_outcomes(task.invoice, user),
                "next_required": ["re_phone"],
                "url": E.lead_url(task.invoice_id),
            }
        )


class TaskDoneView(_TaskView):
    """POST {note?, outcome?, next_task?} -> {task, by_name, invoice, next_task,
    closed_tasks}; 409 already done, 403 not the user's task, 400 {detail, field}."""

    def post(self, request, pk):
        user = self.require_site_perm("call_center.view_invoice")
        data = _dict_body(request)
        outcome = data.get("outcome")
        if outcome is not None and not isinstance(outcome, str):
            return _bad("Keyingi bosqich noto'g'ri", "outcome")
        next_task = data.get("next_task")
        if next_task is not None:
            if not isinstance(next_task, dict):
                return _bad("Qayta qo'ng'iroq vaqti noto'g'ri", "next_task")
            next_task = dict(next_task)
            if next_task.get("due_at") is not None:
                try:
                    next_task["due_at"] = datetime.fromisoformat(str(next_task["due_at"]))
                except ValueError:
                    return _bad("Qayta qo'ng'iroq vaqti noto'g'ri", "next_task")
        res = S.complete_task(
            self.get_task(pk),
            by=user,
            note=str(data.get("note") or ""),
            outcome=outcome,
            next_task=next_task,
        )
        return Response(
            {
                "task": dto.task_dto(res.task),
                "by_name": dto.user_ref(user)["name"],
                "invoice": dto.lead_brief(res.invoice),
                "next_task": dto.task_dto(res.next_task) if res.next_task else None,
                "closed_tasks": res.closed_tasks,
            }
        )


class TaskSnoozeView(_TaskView):
    """POST {preset: 1h|tomorrow} -> {task}; 409 already done."""

    def post(self, request, pk):
        user = self.require_site_perm("call_center.view_invoice")
        task = S.snooze_task(self.get_task(pk), by=user, preset=_dict_body(request).get("preset"))
        return Response({"task": dto.task_dto(task)})
