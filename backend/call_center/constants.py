from django.db.models import IntegerChoices, TextChoices
from unfold.enums import ActionVariant


class SolutionChoice(IntegerChoices):
    declined = (-1, "Сотув амалга ошмади")
    dont_need = (0, "Керак эмас")
    re_phone = (1, "Қайта телефон қилиш")
    given_info = (2, "Телеграмда маълумот берилди")
    given_location = (3, "Мижоздан локация олиш")
    price_problem = (4, "Нархи қониқтирмади")
    go_for_measured = (5, "Замерга борилади")
    sold_out = (6, "Сотилди")

    @classmethod
    def icon(cls, solution):
        return {
            cls.declined: "close",
            cls.dont_need: "close",
            cls.re_phone: "warning",
            cls.given_info: "info",
            cls.given_location: "info",
            cls.price_problem: "close",
            cls.go_for_measured: "check",
            cls.sold_out: "done_all",
        }[solution]

    @classmethod
    def colors(cls):
        return {
            cls.declined: ActionVariant.DANGER,
            cls.dont_need: ActionVariant.DANGER,
            cls.price_problem: ActionVariant.DANGER,
            cls.re_phone: ActionVariant.WARNING,
            cls.given_info: ActionVariant.INFO,
            cls.given_location: ActionVariant.INFO,
            cls.go_for_measured: ActionVariant.SUCCESS,
            cls.sold_out: ActionVariant.SUCCESS,
        }

    @classmethod
    def variant(cls, solution):
        return cls.colors()[solution]


class LeadSource(TextChoices):
    """Where the client came from (Invoice.source)."""

    telegram = ("telegram", "Telegram")
    instagram = ("instagram", "Instagram")
    phone = ("phone", "Telefon qo'ng'iroq")
    showroom = ("showroom", "Do'konga keldi (showroom)")
    recommendation = ("recommendation", "Tavsiya")
    other = ("other", "Boshqa")


class NoteKind(TextChoices):
    note = ("note", "Izoh")
    solution = ("solution", "Javob kodi")
    assigned = ("assigned", "Mas'ul")
    source = ("source", "Manba")
    location = ("location", "Lokatsiya")
    metering = ("metering", "O'lchov")


# Leads in these answers (None = "Yangi") must always have an open task.
ACTIVE_SOLUTIONS = (
    None,
    SolutionChoice.re_phone,
    SolutionChoice.given_info,
    SolutionChoice.given_location,
)
