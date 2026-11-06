"""Stage 2 (dizayn va narx): the shared fields of Design / Price and the short «brief»
shown on a lead, a metering and the «Mijozga ko'rsatish» page."""

from rest_framework import serializers

from metering import services as metering_services
from metering.constants import OfferStage, stage_label
from metering.models import OfferAnswer

from .common import UserShortSerializer

ANSWER_LABELS = {
    "design": {
        "approved": "Tasdiqladi",
        "changes": "O'zgartirish kerak",
        "declined": "Rad etdi",
    },
    "price": {
        "approved": "Rozi",
        "recalc": "Qayta hisoblash",
        "declined": "Narxi qoniqtirmadi",
    },
}


def _iso(value):
    return value.isoformat() if value else None


def _user(user):
    return UserShortSerializer(user).data if user is not None else None


def now_of(context) -> object:
    """One clock reading per serialization run."""
    if "_offer_now" not in context:
        context["_offer_now"] = metering_services._now()
    return context["_offer_now"]


def is_offer_overdue(obj, now) -> bool:
    return obj.stage == OfferStage.work and obj.due_at is not None and obj.due_at < now


def last_comment(metering, kind) -> str | None:
    """The newest non-empty comment of this kind (uses a prefetched `offer_answers`)."""
    best = None
    for a in metering.offer_answers.all():
        if (
            a.kind == kind
            and a.comment
            and (best is None or (a.created_at, a.pk) > (best.created_at, best.pk))
        ):
            best = a
    return best.comment if best else None


def offer_brief(obj, kind, context) -> dict | None:
    """{id, stage, stage_label, due_at, done_at, is_overdue, user, round, last_comment}"""
    if obj is None:
        return None
    return {
        "id": obj.pk,
        "stage": obj.stage,
        "stage_label": stage_label(obj.stage),
        "due_at": _iso(obj.due_at),
        "done_at": _iso(obj.done_at),
        "is_overdue": is_offer_overdue(obj, now_of(context)),
        "user": _user(obj.user),
        "round": obj.round,
        "last_comment": last_comment(obj.metering, kind),
    }


class OfferAnswerSerializer(serializers.ModelSerializer):
    answer_label = serializers.SerializerMethodField()
    by = serializers.SerializerMethodField()

    class Meta:
        model = OfferAnswer
        fields = ["id", "round", "answer", "answer_label", "comment", "due_at", "by", "created_at"]
        read_only_fields = fields

    def get_answer_label(self, obj):
        return ANSWER_LABELS.get(obj.kind, {}).get(obj.answer, obj.answer)

    def get_by(self, obj):
        return _user(obj.by)


class OfferFieldsMixin(serializers.Serializer):
    """Fields Design and Price share (stage 2). Needs `metering__manager` and
    `metering__measurer` select_related for a stable query count."""

    kind = ""  # "design" | "price"
    stage_label = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()
    manager = serializers.SerializerMethodField()
    measurer = serializers.SerializerMethodField()
    last_comment = serializers.SerializerMethodField()
    client_result = serializers.SerializerMethodField()
    result_note = serializers.SerializerMethodField()

    OFFER_FIELDS = [
        "stage",
        "stage_label",
        "due_at",
        "assigned_at",
        "done_at",
        "round",
        "rev",
        "is_overdue",
        "manager",
        "measurer",
        "last_comment",
        "client_result",
        "result_note",
    ]

    def get_stage_label(self, obj):
        return stage_label(obj.stage)

    def get_is_overdue(self, obj):
        return is_offer_overdue(obj, now_of(self.context))

    def get_manager(self, obj):
        return _user(obj.metering.manager) if obj.metering else None

    def get_measurer(self, obj):
        return _user(obj.metering.measurer) if obj.metering else None

    def get_last_comment(self, obj):
        return last_comment(obj.metering, self.kind) if obj.metering else None

    def get_client_result(self, obj):
        return obj.metering.client_result if obj.metering else ""

    def get_result_note(self, obj):
        return obj.metering.result_note if obj.metering else ""
