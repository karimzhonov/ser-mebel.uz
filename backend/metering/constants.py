from django.db.models import TextChoices
from unfold.enums import ActionVariant

METERING_CHANGE_STATUS_PERMISSION = "change_status"
METERING_MANAGE_PERMISSION = "manage_metering"
METERING_PRESENT_PERMISSION = "present_to_client"
METERING_MAX_UPLOAD_MB = 500


class NextStep(TextChoices):
    """What happens after the measurement (set when the metering is finished)."""

    design_price = ("design_price", "Dizayn + narx")
    price = ("price", "Faqat narx")


class OfferStage(TextChoices):
    """Where a Design / Price is (stage 2: dizayn va narx)."""

    work = ("work", "Ishda")
    review = ("review", "Mijozda — javob kutilmoqda")
    approved = ("approved", "Tasdiqlandi")
    declined = ("declined", "Rad etildi")
    cancelled = ("cancelled", "Bekor")


class ClientResult(TextChoices):
    """The client's final answer, kept on the metering."""

    agreed = ("agreed", "Mijoz rozi")
    design_declined = ("design_declined", "Dizaynni rad etdi")
    price_declined = ("price_declined", "Narxi qoniqtirmadi")


class OfferAnswerKind(TextChoices):
    """The manager's answer to a design / price (price says "recalc" for "changes")."""

    approved = ("approved", "Tasdiqladi")
    changes = ("changes", "O'zgartirish kerak")
    recalc = ("recalc", "Qayta hisoblash")
    declined = ("declined", "Rad etdi")


# stages in which the work is done and the client has not (finally) answered
OFFER_ARCHIVE = ("approved", "declined", "cancelled")


class MeteringStatus(TextChoices):
    created = ("created", "Заявка олинди")
    dont_need = ("dont_need", "Отмен болди")
    other_day = ("other_day", "Бошқа кунга ўзгартирилди")
    metering_done = ("metering_done", "Замерга борилди")
    done = ("done", "Бажарилди")
    sold_out = ("sold_out", "Сотилди")

    @classmethod
    def active_statuses(cls):
        return [cls.created, cls.other_day, cls.metering_done]

    @classmethod
    def archive_statuses(cls):
        return [cls.dont_need, cls.done, cls.sold_out]

    @classmethod
    def icon(cls, status):
        return {
            cls.metering_done: "info",
            cls.created: "add",
            cls.dont_need: "close",
            cls.other_day: "warning",
            cls.done: "check",
            cls.sold_out: "done_all",
        }[status]

    @classmethod
    def colors(cls):
        return {
            cls.metering_done: ActionVariant.INFO,
            cls.created: ActionVariant.INFO,
            cls.dont_need: ActionVariant.DANGER,
            cls.other_day: ActionVariant.WARNING,
            cls.done: ActionVariant.SUCCESS,
            cls.sold_out: ActionVariant.SUCCESS,
        }

    @classmethod
    def variant(cls, status):
        return cls.colors()[status]
