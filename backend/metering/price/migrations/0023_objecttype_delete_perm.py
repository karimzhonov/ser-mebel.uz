"""Whoever may add or edit objects («Mahsulotlar» → Obyekt) may now delete them too
(«O'chirish» archives an object old calculations still use). Groups and users that
hold price.add_objecttype or price.change_objecttype get price.delete_objecttype."""

from django.conf import settings
from django.db import migrations
from django.db.models import Q


def grant(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))

    ct, _ = ContentType.objects.get_or_create(app_label="price", model="objecttype")
    delete, _ = Permission.objects.get_or_create(
        content_type=ct, codename="delete_objecttype", defaults={"name": "Can delete object type"}
    )
    managers = Q(codename__in=["add_objecttype", "change_objecttype"], content_type=ct)
    perms = list(Permission.objects.filter(managers))
    if not perms:
        return
    for g in Group.objects.filter(permissions__in=perms).distinct():
        g.permissions.add(delete)
        print(f"  {g.name}: + price.delete_objecttype")
    for u in User.objects.filter(user_permissions__in=perms).distinct():
        u.user_permissions.add(delete)


class Migration(migrations.Migration):

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("price", "0022_objecttype_archived_bedroom"),
    ]

    operations = [migrations.RunPython(grant, migrations.RunPython.noop)]
