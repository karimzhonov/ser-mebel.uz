from django.urls import reverse_lazy
from metering.constants import MeteringStatus
from metering.price.models import ObjectType


def get_tabs(request):
    return [
        {
            'models': [
                'metering.metering'
            ],
            'items': [
                {
                    "title": 'Активний',
                    "link": reverse_lazy("admin:metering_metering_changelist", query={'status': ','.join(MeteringStatus.active_statuses())}),
                    "permission": lambda request: True,
                },
                {
                    "title": 'Архив',
                    "link": reverse_lazy("admin:metering_metering_changelist", query={'status': ','.join(MeteringStatus.archive_statuses())}),
                    "permission": lambda request: True,
                }
            ]
        },
        {
            'models': [
                'design.design'
            ],
            'items': [
                {
                    "title": 'Активний',
                    "link": reverse_lazy("admin:design_design_changelist", query={'confirm': False}),
                    "permission": lambda request: True,
                },
                {
                    "title": 'Архив',
                    "link": reverse_lazy("admin:design_design_changelist", query={'confirm': True}),
                    "permission": lambda request: True,
                }
            ]
        },
        {
            'models': [
                'price.price'
            ],
            'items': [
                {
                    "title": 'Активний',
                    "link": reverse_lazy("admin:price_price_changelist", query={'done': False}),
                    "permission": lambda request: True,
                },
                {
                    "title": 'Архив',
                    "link": reverse_lazy("admin:price_price_changelist", query={'done': True}),
                    "permission": lambda request: True,
                }
            ]
        },
        {
            'models': [
                'price.inventorytype',
            ],
            'items': [
                {
                    "title": obj.name,
                    "link": reverse_lazy("admin:price_inventorytype_changelist", query={'obj_id': obj.pk}),
                    "permission": lambda request: True,
                } for obj in ObjectType.objects.all()
            ]
        },
        {
            'models': [
                'detailing.detailing'
            ],
            'items': [
                {
                    "title": 'Активний',
                    "link": reverse_lazy("admin:detailing_detailing_changelist", query={'working_done': False}),
                    "permission": lambda request: True,
                },
                {
                    "title": 'Архив',
                    "link": reverse_lazy("admin:detailing_detailing_changelist", query={'working_done': True}),
                    "permission": lambda request: True,
                }
            ]
        },
        {
            'models': [
                'rover.rover'
            ],
            'items': [
                {
                    "title": 'Активний',
                    "link": reverse_lazy("admin:rover_rover_changelist", query={'done': False}),
                    "permission": lambda request: True,
                },
                {
                    "title": 'Архив',
                    "link": reverse_lazy("admin:rover_rover_changelist", query={'done': True}),
                    "permission": lambda request: True,
                }
            ]
        },
        {
            'models': [
                'painter.painter'
            ],
            'items': [
                {
                    "title": 'Активний',
                    "link": reverse_lazy("admin:painter_painter_changelist", query={'done': False}),
                    "permission": lambda request: True,
                },
                {
                    "title": 'Архив',
                    "link": reverse_lazy("admin:painter_painter_changelist", query={'done': True}),
                    "permission": lambda request: True,
                }
            ]
        },
        {
            'models': [
                'assembly.assembly'
            ],
            'items': [
                {
                    "title": 'Активний',
                    "link": reverse_lazy("admin:assembly_assembly_changelist", query={'installing_done': False}),
                    "permission": lambda request: True,
                },
                {
                    "title": 'Архив',
                    "link": reverse_lazy("admin:assembly_assembly_changelist", query={'installing_done': True}),
                    "permission": lambda request: True,
                }
            ]
        }
    ]