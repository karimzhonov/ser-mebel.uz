from django.db.models import TextChoices
from unfold.enums import ActionVariant

METERING_CHANGE_STATUS_PERMISSION = 'change_status'


class MeteringStatus(TextChoices):
    created = ('created', 'Создан')
    dont_need = ('dont_need', 'Керак эмас')
    re_phone = ('re_phone', 'Қайта телефон қилиш')
    price_problem = ('price_problem', 'Нархи қониқтирмади')
    sold_out = ('sold_out', 'Сотилди')

    @classmethod
    def get_order(cls):
        return [
            cls.created,
            cls.dont_need,
            cls.re_phone,
            cls.price_problem,
            cls.sold_out,
        ]

    @classmethod
    def icon(cls, status):
        return {
            cls.created: 'close',
            cls.dont_need: 'close',
            cls.re_phone: 'warning',
            cls.price_problem: 'close',
            cls.sold_out: 'check'
        }[status]
    
    @classmethod
    def colors(cls):
        return {
            cls.created: ActionVariant.INFO,
            cls.price_problem: ActionVariant.DANGER,
            cls.dont_need: ActionVariant.DANGER,
            cls.re_phone: ActionVariant.WARNING,
            cls.sold_out: ActionVariant.SUCCESS
        }

    @classmethod
    def variant(cls, status):
        return cls.colors()[status]