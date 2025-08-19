from django.db.models import TextChoices
from django.utils.translation import gettext_lazy as _

ORDER_CHANGE_STATUS_PERMISSION = 'change_status_order'
ORDER_REVERSE_STATUS_PERMISSION = 'reverse_status_order'
ORDER_VIEW_PRICE_PERMISSION = 'view_order_price'


class OrderStatus(TextChoices):
    CREATED = 'created', _('Создан')
    DETAILING = 'detailing', _('Деталировка')
    WORKING = 'working', _('Заказ на сырье')
    ASSEMBLY = 'assembly', _('Сборка')
    INSTALLING = 'installing', _('Установка')
    DONE = 'done', _('Готов')

    @classmethod
    def get_order(cls):
        return [cls.CREATED, cls.DETAILING, cls.WORKING, cls.ASSEMBLY, cls.INSTALLING, cls.DONE]
    
    @classmethod
    def get_sev(cls, status):
        return {
            OrderStatus.CREATED: "info",
            OrderStatus.DETAILING: "info",
            OrderStatus.WORKING: "warning",
            OrderStatus.ASSEMBLY:  "warning",
            OrderStatus.INSTALLING:  "warning",
            OrderStatus.DONE:  "success",
        }[status]
    
    @classmethod
    def icon(cls, status):
        return {
            OrderStatus.CREATED: "add",
            OrderStatus.DETAILING: "book",
            OrderStatus.WORKING: "monitor",
            OrderStatus.ASSEMBLY:  "bolt",
            OrderStatus.INSTALLING:  "build",
            OrderStatus.DONE:  "check",
        }[status]

    @classmethod
    def next_status(cls, current):
        order = cls.get_order()
        try:
            idx = order.index(current)
            return order[idx + 1]
        except (ValueError, IndexError):
            return None

    @classmethod
    def previous_status(cls, current):
        order = cls.get_order()
        try:
            idx = order.index(current)
            return order[idx - 1] if idx > 0 else None
        except (ValueError, IndexError):
            return None
