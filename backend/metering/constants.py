from django.db.models import TextChoices
from unfold.enums import ActionVariant

METERING_CHANGE_STATUS_PERMISSION = 'change_status'


class MeteringStatus(TextChoices):
    created = ('created', 'Заявка олинди')
    dont_need = ('dont_need', 'Отмен болди')
    other_day = ('other_day', 'Бошқа кунга ўзгартирилди')
    done = ('done', 'Бажарилди')
    sold_out = ('sold_out', 'Сотилди')

    @classmethod
    def active_statuses(cls):
        return [cls.created, cls.other_day]
    
    @classmethod
    def archive_statuses(cls):
        return [cls.dont_need, cls.done, cls.sold_out]

    @classmethod
    def icon(cls, status):
        return {
            cls.created: 'add',
            cls.dont_need: 'close',
            cls.other_day: 'warning',
            cls.done: 'check',
            cls.sold_out: 'done_all',
        }[status]
    
    @classmethod
    def colors(cls):
        return {
            cls.created: ActionVariant.INFO,
            cls.dont_need: ActionVariant.DANGER,
            cls.other_day: ActionVariant.WARNING,
            cls.done: ActionVariant.SUCCESS,
            cls.sold_out: ActionVariant.SUCCESS,
        }

    @classmethod
    def variant(cls, status):
        return cls.colors()[status]