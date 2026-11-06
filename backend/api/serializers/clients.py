from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from phonenumber_field.serializerfields import PhoneNumberField
from rest_framework import serializers

from call_center.constants import ACTIVE_SOLUTIONS, LeadSource, SolutionChoice
from call_center.dto import dt, user_ref
from call_center.models import Invoice
from call_center.services import invoice_is_editable
from client.models import Client
from metering.models import Metering

from .offers import offer_brief

from .. import i18n as uz
from .common import ClientShortSerializer, LocationFieldsMixin, LocationInputMixin


class ClientSerializer(serializers.ModelSerializer):
    phone = PhoneNumberField(region="UZ", read_only=True)
    orders_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = Client
        fields = ["phone", "fio", "created_at", "orders_count"]
        read_only_fields = ["created_at"]


class InvoiceSerializer(LocationFieldsMixin, serializers.ModelSerializer):
    client = ClientShortSerializer(read_only=True)
    solution_label = serializers.SerializerMethodField()
    is_editable = serializers.SerializerMethodField()
    metering_id = serializers.SerializerMethodField()
    metering = serializers.SerializerMethodField()
    source_label = serializers.SerializerMethodField()
    assigned_to = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    next_task = serializers.SerializerMethodField()
    open_tasks = serializers.SerializerMethodField()
    needs_task = serializers.SerializerMethodField()
    estimate = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            "id",
            "client",
            "create_date",
            "update_date",
            "desc",
            "address",
            "address_link",
            "lat",
            "lon",
            "map_url",
            "solution",
            "solution_label",
            "is_editable",
            "metering_id",
            "metering",
            "source",
            "source_label",
            "assigned_to",
            "created_by",
            "next_task",
            "open_tasks",
            "needs_task",
            "estimate",
        ]
        read_only_fields = [
            "create_date",
            "update_date",
            "solution",
            "source",
            "address",
            "address_link",
        ]

    def get_estimate(self, obj):
        """The lead's approximate price: {id, stage, stage_label, total} or null."""
        from metering.constants import stage_label

        try:
            p = obj.estimate
        except ObjectDoesNotExist:
            return None
        if p is None:
            return None
        current = getattr(obj, "metering", None) if hasattr(obj, "metering") else None
        if p.stage != "estimate" and (current is None or p.metering_id != current.pk):
            return None  # the price of an earlier (let go) zamer
        total = None
        if p.price is not None and p.price.amount is not None:
            total = {"amount": float(p.price.amount), "currency": str(p.price.currency)}
        return {"id": p.pk, "stage": p.stage, "stage_label": stage_label(p.stage), "total": total}

    def get_solution_label(self, obj):
        return uz.solution(obj.solution)

    def get_source_label(self, obj):
        return uz.lead_source(obj.source)

    def get_assigned_to(self, obj):
        return user_ref(obj.assigned_to)

    def get_created_by(self, obj):
        return user_ref(obj.created_by)

    def _tasks(self, obj):
        """(next open task as {id, text, due_at}|None, number of open tasks). The list
        view annotates these; a single object is asked."""
        if hasattr(obj, "open_tasks"):
            count = obj.open_tasks or 0
            if not obj.next_task_id:
                return None, count
            return {
                "id": obj.next_task_id,
                "text": obj.next_task_text,
                "due_at": dt(obj.next_due),
            }, count
        cache = obj.__dict__.get("_crm_tasks")
        if cache is None:
            open_ = list(obj.tasks.filter(done_at__isnull=True).order_by("due_at", "pk"))
            first = open_[0] if open_ else None
            nxt = (
                {"id": first.pk, "text": first.text, "due_at": dt(first.due_at)} if first else None
            )
            cache = obj.__dict__["_crm_tasks"] = (nxt, len(open_))
        return cache

    def get_next_task(self, obj):
        return self._tasks(obj)[0]

    def get_open_tasks(self, obj):
        return self._tasks(obj)[1]

    def get_needs_task(self, obj):
        return obj.solution in ACTIVE_SOLUTIONS and self._tasks(obj)[1] == 0

    def get_is_editable(self, obj):
        return invoice_is_editable(obj)

    def get_metering_id(self, obj):
        metering = getattr(obj, "metering", None)
        return metering.pk if isinstance(metering, Metering) else None

    def get_metering(self, obj):
        """The lead's zamer in short (the lead card shows it without a second request)."""
        from core.i18n import metering_status

        m = getattr(obj, "metering", None)
        if not isinstance(m, Metering):
            return None
        measurer = m.measurer
        return {
            "id": m.pk,
            "status": m.status,
            "status_label": metering_status(m.status),
            "date_time": m.date_time,
            "measurer": (
                {"id": measurer.pk, "name": measurer.name or str(measurer.phone)}
                if measurer
                else None
            ),
            "result_note": m.result_note,
            "cancel_reason": m.cancel_reason,
            "next_step": m.next_step,
            "folder": m.folder_id,
            "manager": (
                {"id": m.manager.pk, "name": m.manager.name or str(m.manager.phone)}
                if m.manager
                else None
            ),
            "client_result": m.client_result,
            "design": offer_brief(getattr(m, "design", None), "design", self.context),
            "price": offer_brief(getattr(m, "price", None), "price", self.context),
        }


class InvoiceCreateSerializer(LocationInputMixin, serializers.Serializer):
    fio = serializers.CharField(max_length=255)
    phone = PhoneNumberField(region="UZ")
    desc = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    source = serializers.ChoiceField(choices=LeadSource.choices)
    address = serializers.CharField(max_length=255, required=False, allow_blank=True)
    # eligibility (may change invoices) is checked by call_center.services
    assigned_to = serializers.PrimaryKeyRelatedField(
        queryset=get_user_model().objects.all(), required=False, allow_null=True
    )
    task_text = serializers.CharField(
        max_length=500, required=False, allow_blank=True, allow_null=True
    )
    task_due_at = serializers.DateTimeField(required=False, allow_null=True)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        text, due = attrs.pop("task_text", None), attrs.pop("task_due_at", None)
        if due is None and text:
            raise serializers.ValidationError({"task_due_at": uz.ERROR_CODE["required"]})
        if due is not None:
            attrs["task"] = {"text": text, "due_at": due}
        return attrs


class InvoiceSolutionSerializer(serializers.Serializer):
    solution = serializers.ChoiceField(choices=SolutionChoice.choices)
