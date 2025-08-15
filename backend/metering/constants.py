from django.db.models import TextChoices
from unfold.enums import ActionVariant

METERING_CHANGE_STATUS_PERMISSION = 'change_status'


class MeteringStatus(TextChoices):
    created = ('created', 'Заявка олинди')
    dont_need = ('dont_need', 'Отмен болди')
    other_day = ('re_phone', 'Бошқа кунга ўзгартирилди')
    done = ('done', 'Бажарилди')

    @classmethod
    def get_order(cls):
        return [
            cls.created,
            cls.dont_need,
            cls.other_day,
            cls.done,
        ]

    @classmethod
    def icon(cls, status):
        return {
            cls.created: 'add',
            cls.dont_need: 'close',
            cls.other_day: 'warning',
            cls.done: 'check'
        }[status]
    
    @classmethod
    def colors(cls):
        return {
            cls.created: ActionVariant.INFO,
            cls.dont_need: ActionVariant.DANGER,
            cls.other_day: ActionVariant.WARNING,
            cls.done: ActionVariant.SUCCESS
        }

    @classmethod
    def variant(cls, status):
        return cls.colors()[status]