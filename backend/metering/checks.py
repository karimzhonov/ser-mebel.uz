from django.core.checks import Tags, Warning, register


@register(Tags.models)
def no_measurer_check(app_configs, **kwargs):
    """Warn (never fail) when nobody can be sent to measure."""
    from django.db import DatabaseError

    from .services import measurers

    try:
        empty = not measurers().exists()
    except DatabaseError:  # tables not migrated yet
        return []
    if empty:
        return [
            Warning(
                "No active staff user holds oauth.user_metering (measurer).",
                hint="Give a staff user the «Metering» permission; until then zamers are "
                "created without a measurer.",
                id="metering.W001",
            )
        ]
    return []
