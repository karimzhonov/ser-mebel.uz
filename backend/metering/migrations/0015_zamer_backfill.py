from datetime import datetime

from django.db import migrations
from django.db.models import F, Q

OPEN = ["created", "other_day"]
ACTIVE = ["created", "other_day", "metering_done"]


def backfill(apps, schema_editor):
    """Legacy meterings had no measurer: when the company has exactly one explicit
    holder of oauth.user_metering, they get the open meterings. Only meterings that are
    still in the future are marked as announced (scheduled_at), so the first reminder
    scan does not nag about old ones."""
    User = apps.get_model("oauth", "User")
    Metering = apps.get_model("metering", "Metering")

    perm = Q(
        user_permissions__codename="user_metering",
        user_permissions__content_type__app_label="oauth",
    ) | Q(
        groups__permissions__codename="user_metering",
        groups__permissions__content_type__app_label="oauth",
    )
    holders = list(User.objects.filter(is_active=True, is_staff=True).filter(perm).distinct()[:2])
    if len(holders) == 1:
        Metering.objects.filter(status__in=ACTIVE, measurer__isnull=True).update(
            measurer=holders[0]
        )
    Metering.objects.filter(
        status__in=OPEN, date_time__gte=datetime.now(), scheduled_at__isnull=True
    ).update(scheduled_at=F("create_date"))


class Migration(migrations.Migration):
    dependencies = [
        ("metering", "0014_zamer_stage1"),
        ("oauth", "0010_telegrammember_is_accountant"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
