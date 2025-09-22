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
                        "color": "gradient-1"
                    },
                    {
                        "title": 'Расходы',
                        "icon": "upload",
                        "link": reverse_lazy("admin:accounting_expense_changelist"),
                        "permission": lambda request: request.user.has_perm('accounting.view_expense'),
                        "color": "gradient-2"
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
                        "color": "gradient-3"
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
                        "color": "gradient-4"
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
                        "color": "gradient-5"
                    },
                    {
                        "title": "Дизайн",
                        "icon": "brush",
                        "link": reverse_lazy("admin:design_design_changelist", query={'confirm': False}),
                        "permission": lambda request: request.user.has_perm('design.view_design'),
                        "color": "gradient-6"
                    },
                    {
                        "title": "Нарх чикариш",
                        "icon": "attach_money",
                        "link": reverse_lazy("admin:price_price_changelist", query={'done': False}),
                        "permission": lambda request: request.user.has_perm('price.view_price'),
                        "color": "gradient-7"
                    },
                    {
                        "title": "Товари",
                        "icon": "inventory_2",
                        "link": reverse_lazy("admin:price_inventorytype_changelist", query={'obj_id': getattr(ObjectType.objects.all().first(), 'pk', '')}),
                        "permission": lambda request: request.user.has_perm('price.view_inventorytype'),
                        "color": "gradient-8"
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
                        "color": "gradient-9",
                    },
                    {
                        "title": "Деталировка / Производстьво",
                        "icon": "book",
                        "link": reverse_lazy("admin:detailing_detailing_changelist", query={'working_done': False}),
                        "permission": lambda request: request.user.has_perm('detailing.view_detailing'),
                        "color": "gradient-10 col-span-2",
                    },
                    {
                        "title": "Ровер",
                        "icon": "design_services",
                        "link": reverse_lazy("admin:rover_rover_changelist", query={'done': False}),
                        "permission": lambda request: request.user.has_perm('rover.view_rover'),
                        "color": "gradient-11"
                    },
                    {
                        "title": "Моляр",
                        "icon": "brush",
                        "link": reverse_lazy("admin:painter_painter_changelist", query={'done': False}),
                        "permission": lambda request: request.user.has_perm('painter.view_painter'),
                        "color": "gradient-12"
                    },
                    {
                        "title": "Сборка / Установка",
                        "icon": "bolt",
                        "link": reverse_lazy("admin:assembly_assembly_changelist", query={'installing_done': False}),
                        "permission": lambda request: request.user.has_perm('assembly.view_assembly'),
                        "color": "gradient-13 col-span-2"
                    }
                ],
            },
        ],
    }