from django.apps import AppConfig


class MeteringConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "metering"
    verbose_name = "Замер"

    def ready(self):
        from . import checks  # noqa: F401
