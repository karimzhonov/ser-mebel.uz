from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _sync_schedule(**kwargs):
    from .schedule import sync_periodic_tasks

    sync_periodic_tasks()


class AccountingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounting'

    def ready(self):
        post_migrate.connect(_sync_schedule, sender=self, dispatch_uid="accounting_schedule")

        from . import signals

        signals.connect()
