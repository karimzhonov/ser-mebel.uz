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


@register(Tags.models)
def no_manager_check(app_configs, **kwargs):
    """Warn (never fail) when nobody may show the design / price to the client."""
    from django.db import DatabaseError

    from .services import managers

    try:
        empty = not managers().exists()
    except DatabaseError:  # tables not migrated yet
        return []
    if empty:
        return [
            Warning(
                "No active staff user holds metering.present_to_client (manager).",
                hint="Give a staff user the «Menejer» permission; until then «Bajarildi» "
                "finishes without a manager and nobody is told a design / price is ready.",
                id="metering.W002",
            )
        ]
    return []
