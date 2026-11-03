"""Call-centre CRM: notes, tasks, lead updates, timeline."""

from django.contrib.auth import get_user_model
from rest_framework import serializers

from call_center.constants import LeadSource
from call_center.dto import dt, user_ref
from call_center.services import OUTCOME_KEYS

from .. import i18n as uz

User = get_user_model()


class NoteCreateSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=5000)


class TaskCreateSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    due_at = serializers.DateTimeField()
    assigned_to = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), required=False, allow_null=True
    )


class NextTaskSerializer(serializers.Serializer):
    """The next call: exactly one of `due_at` / `preset`."""

    text = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
    due_at = serializers.DateTimeField(required=False)
    preset = serializers.ChoiceField(choices=["1h", "today", "tomorrow"], required=False)

    def validate(self, attrs):
        if bool(attrs.get("due_at")) == bool(attrs.get("preset")):
            raise serializers.ValidationError(
                {"due_at": "due_at yoki preset dan birini ko'rsating."}
            )
        return attrs


class TaskDoneSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=5000, required=False, allow_blank=True, default="")
    outcome = serializers.ChoiceField(choices=OUTCOME_KEYS, required=False, allow_null=True)
    next_task = NextTaskSerializer(required=False, allow_null=True)


class TaskRescheduleSerializer(serializers.Serializer):
    due_at = serializers.DateTimeField(required=False)
    preset = serializers.ChoiceField(choices=["1h", "today", "tomorrow"], required=False)

    def validate(self, attrs):
        if bool(attrs.get("due_at")) == bool(attrs.get("preset")):
            raise serializers.ValidationError(
                {"due_at": "due_at yoki preset dan birini ko'rsating."}
            )
        return attrs


class LeadUpdateSerializer(serializers.Serializer):
    assigned_to = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), required=False, allow_null=True
    )
    source = serializers.ChoiceField(choices=LeadSource.choices, required=False)


class InvoiceTaskSerializer(serializers.Serializer):
    """A task with the lead it belongs to (the agenda lists them across leads)."""

    id = serializers.IntegerField()
    text = serializers.CharField()
    due_at = serializers.SerializerMethodField()
    is_done = serializers.SerializerMethodField()
    done_at = serializers.SerializerMethodField()
    created_at = serializers.SerializerMethodField()
    assigned = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    invoice = serializers.SerializerMethodField()

    def get_due_at(self, obj):
        return dt(obj.due_at)

    def get_done_at(self, obj):
        return dt(obj.done_at)

    def get_created_at(self, obj):
        return dt(obj.created_at)

    def get_is_done(self, obj):
        return obj.done_at is not None

    def get_assigned(self, obj):
        return user_ref(obj.assigned_to)

    def get_created_by(self, obj):
        return user_ref(obj.created_by)

    def get_invoice(self, obj):
        inv = obj.invoice
        return {
            "id": inv.pk,
            "client": {"fio": inv.client.fio, "phone": str(inv.client.phone)},
            "source": inv.source,
            "source_label": uz.lead_source(inv.source),
            "solution": inv.solution,
            "solution_label": uz.solution(inv.solution),
            "address": inv.address or "",
            "has_point": inv.lat is not None and inv.lon is not None,
        }


class TimelineEntrySerializer(serializers.Serializer):
    """type: created | note | task_created | task_done | metering | order.
    `kind` (note/solution/assigned/source) is set for type=note only."""

    type = serializers.CharField()
    at = serializers.SerializerMethodField()
    author = serializers.DictField(allow_null=True)
    kind = serializers.CharField(allow_null=True)
    text = serializers.CharField(allow_blank=True)
    meta = serializers.DictField()
    task = serializers.DictField(allow_null=True)
    link = serializers.DictField(allow_null=True)

    def get_at(self, obj):
        return dt(obj["at"])
