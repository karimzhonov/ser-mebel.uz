"""Bot API - CRM: a salesperson adds a lead from Telegram and answers task reminders.

The actor is the panel user linked to the Telegram account (oauth.User.telegram_id);
call_center.services decides, the bot only relays.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from phonenumber_field.phonenumber import PhoneNumber
from phonenumbers import NumberParseException
from rest_framework.exceptions import NotFound, ParseError
from rest_framework.response import Response

from call_center import dto
from call_center import events as E
from call_center import services as S
from call_center.constants import LeadSource
from call_center.models import Invoice, InvoiceTask
from core.exceptions import ServiceError

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


class DueParseView(BotAPIView):
    """POST {text} -> {due_at}; 400 {detail, field: "remind"} when it can't be read."""

    def post(self, request):
        self.require_site_perm("call_center.add_invoice")
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


class TaskDoneView(_TaskView):
    """POST {note?} -> {task, by_name}; 409 already done, 403 not the user's task."""

    def post(self, request, pk):
        user = self.require_site_perm("call_center.view_invoice")
        task = S.complete_task(
            self.get_task(pk), by=user, note=str(_dict_body(request).get("note") or "")
        )
        return Response({"task": dto.task_dto(task), "by_name": dto.user_ref(user)["name"]})


class TaskSnoozeView(_TaskView):
    """POST {preset: 1h|tomorrow} -> {task}; 409 already done."""

    def post(self, request, pk):
        user = self.require_site_perm("call_center.view_invoice")
        task = S.snooze_task(self.get_task(pk), by=user, preset=_dict_body(request).get("preset"))
        return Response({"task": dto.task_dto(task)})
