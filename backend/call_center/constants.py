from django.db.models import IntegerChoices
from unfold.enums import ActionVariant


class SolutionChoice(IntegerChoices):
    declined = (-1, 'Сотув амалга ошмади')
    dont_need = (0, 'Керак эмас')
    re_phone = (1, 'Қайта телефон қилиш')
    given_info = (2, 'Телеграмда маълумот берилди')
    given_location = (3, 'Локация юборилади')
    price_problem = (4, 'Нархи қониқтирмади')
    go_for_measured = (5, 'Замерга борилади')
    sold_out = (6, 'Сотилди')

    @classmethod
    def icon(cls, solution):
        return {
            cls.declined: 'close',
            cls.dont_need: 'close',
            cls.re_phone: 'warning',
            cls.given_info: 'info',
            cls.given_location: 'info',
            cls.price_problem: 'close',
            cls.go_for_measured: 'check',
            cls.sold_out: 'done_all'
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
            cls.sold_out: ActionVariant.SUCCESS
        }

    @classmethod
    def variant(cls, solution):
        return cls.colors()[solution]

    @classmethod
    def get_order(cls):
        return [
            cls.declined,
            cls.dont_need,
            cls.price_problem,
            cls.re_phone,
            cls.given_info,
            cls.given_location,
            cls.go_for_measured,
            cls.sold_out,
        ]