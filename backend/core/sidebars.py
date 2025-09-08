from django.urls import reverse_lazy
from metering.constants import MeteringStatus
from metering.price.models import ObjectType


def get_sidebar_items(request):
    return {
        "show_all_applications": lambda request: request.user.is_superuser,
        "navigation": [
            {
                "title": "Бухгалтерия",
                "items": [
                    {
                        "title": 'Приходы',
                        "icon": "download",
                        "link": reverse_lazy("admin:accounting_income_changelist"),
                        "permission": lambda request: request.user.has_perm('accounting.view_income'),
                    },
                    {
                        "title": 'Расходы',
                        "icon": "upload",
                        "link": reverse_lazy("admin:accounting_expense_changelist"),
                        "permission": lambda request: request.user.has_perm('accounting.view_expense'),
                    },
                ]
            },
            {
                "title": "Клиент база",
                "items": [
                    {
                        "title": 'Клиенти',
                        "icon": "people",
                        "link": reverse_lazy("admin:client_client_changelist"),
                        "permission": lambda request: request.user.has_perm('client.view_client'),
                    },
                ]
            },
            {
                "title": "Call-center база",
                "items": [
                    {
                        "title": "Call-center",
                        "icon": "phone",
                        "link": reverse_lazy("admin:call_center_invoice_changelist"),
                        "permission": lambda request: request.user.has_perm('call_center.view_invoice'),
                    },
                ]
            },
            {
                "title": "Замер база",
                "items": [
                    {
                        "title": "Замери",
                        "icon": "settings",
                        "link": reverse_lazy("admin:metering_metering_changelist", query={'status': ','.join(MeteringStatus.active_statuses())}),
                        "permission": lambda request: request.user.has_perm('metering.view_metering'),
                    },
                    {
                        "title": "Дизайн",
                        "icon": "brush",
                        "link": reverse_lazy("admin:design_design_changelist", query={'done': False}),
                        "permission": lambda request: request.user.has_perm('design.view_design'),
                    },
                    {
                        "title": "Нарх чикариш",
                        "icon": "attach_money",
                        "link": reverse_lazy("admin:price_price_changelist", query={'done': False}),
                        "permission": lambda request: request.user.has_perm('price.view_price'),
                    },
                    {
                        "title": "Товари",
                        "icon": "inventory_2",
                        "link": reverse_lazy("admin:price_inventorytype_changelist", query={'obj_id': getattr(ObjectType.objects.all().first(), 'pk', '')}),
                        "permission": lambda request: request.user.has_perm('price.view_inventorytype'),
                    },
                ]
            },
            {
                "title": "Заказ база",
                "items": [
                    {
                        "title": "Закази",
                        "icon": "box",
                        "link": reverse_lazy("admin:order_order_changelist"),
                        "permission": lambda request: request.user.has_perm('order.view_order'),
                    },
                    {
                        "title": "Деталировка / Производстьво",
                        "icon": "book",
                        "link": reverse_lazy("admin:detailing_detailing_changelist", query={'working_done': False}),
                        "permission": lambda request: request.user.has_perm('detailing.view_detailing'),
                    },
                    {
                        "title": "Ровер",
                        "icon": "design_services",
                        "link": reverse_lazy("admin:rover_rover_changelist", query={'done': False}),
                        "permission": lambda request: request.user.has_perm('rover.view_rover'),
                    },
                    {
                        "title": "Моляр",
                        "icon": "brush",
                        "link": reverse_lazy("admin:painter_painter_changelist", query={'done': False}),
                        "permission": lambda request: request.user.has_perm('painter.view_painter'),
                    },
                    {
                        "title": "Сборка / Установка",
                        "icon": "bolt",
                        "link": reverse_lazy("admin:assembly_assembly_changelist", query={'installing_done': False}),
                        "permission": lambda request: request.user.has_perm('assembly.view_assembly'),
                    }
                ],
            },
        ],
    }