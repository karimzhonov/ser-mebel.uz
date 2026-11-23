"""Finance inner sections get permissions of their own (Qarzlar, Xulosa, Hamyonlar, ...).

Until now one `view_operation` / `add_operation` opened every finance page. The new
permissions are created here and handed to everyone who could already open that page, so
nobody gains access to a page or loses one on deploy: each new permission derives from one
old one (see FROM below). One deliberate widening: the form dropdowns read `finance/options/`,
which shows the worker roster and cars to add/change_operation holders and the members list to
view_all_operations holders. Groups and users are handled separately (a user's direct permissions and
the permissions of his groups are different holders; the check is `has_perm`, the union).

Idempotent (`ignore_conflicts`), works before `post_migrate` has created the Permission
rows (get_or_create with the exact names Django would use). The reverse deletes only the
13 new permissions (their M2M rows cascade); the old ones are never touched."""

from django.db import migrations

# new permission -> the permissions whose holders receive it (any of them)
FROM = {
    "view_debt": ["view_operation"],
    "view_finance_summary": ["view_operation"],
    "view_finance_wallets": ["view_operation"],
    "view_finance_orders": ["view_operation"],
    "view_worker_card": ["view_operation"],
    "view_advances": ["view_operation"],
    "view_finance_checks": ["view_operation"],
    "view_order_bonus_line": ["view_operation", "view_orderbonus"],
    "add_debt": ["add_operation"],
    "change_advances": ["add_operation"],
    "change_debt": ["change_operation"],
    "delete_debt": ["delete_operation"],
    "view_finance_home": ["view_all_operations"],
}

# (model, codename, name) exactly as Meta / Django's defaults make them
NEW = {
    "operation": {
        "view_finance_home": "Bosh sahifada moliya",
        "view_finance_summary": "Moliya: Xulosa",
        "view_finance_wallets": "Moliya: Hamyonlar",
        "view_finance_orders": "Moliya: Buyurtmalar moliyasi",
        "view_worker_card": "Moliya: Ishchi kartasi",
        "view_advances": "Moliya: Avanslarni ko'rish",
        "change_advances": "Moliya: Avanslarni tasdiqlash",
        "view_finance_checks": "Moliya: Tekshiruv",
        "view_order_bonus_line": "Moliya: Buyurtmadagi bonus",
    },
    "debt": {
        "add_debt": "Can add Qarz",
        "change_debt": "Can change Qarz",
        "delete_debt": "Can delete Qarz",
        "view_debt": "Can view Qarz",
    },
}


def forward(apps, schema_editor):
    ContentType = apps.get_model("contenttypes", "ContentType")
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")
    User = apps.get_model("oauth", "User")

    new = {}
    for model, perms in NEW.items():
        ct, _ = ContentType.objects.get_or_create(app_label="accounting", model=model)
        for codename, name in perms.items():
            perm, _ = Permission.objects.get_or_create(
                content_type=ct, codename=codename, defaults={"name": name}
            )
            new[codename] = perm

    old_names = {c for srcs in FROM.values() for c in srcs}
    old = {
        p.codename: p
        for p in Permission.objects.filter(
            content_type__app_label="accounting", codename__in=old_names
        )
    }

    for through, holder in (
        (Group.permissions.through, "group_id"),
        (User.user_permissions.through, "user_id"),
    ):
        holders = {}  # old codename -> ids holding it
        for codename, perm in old.items():
            holders[codename] = set(
                through.objects.filter(permission_id=perm.pk).values_list(holder, flat=True)
            )
        rows = []
        for codename, sources in FROM.items():
            ids = set().union(*(holders.get(s, set()) for s in sources))
            rows += [through(**{holder: i, "permission_id": new[codename].pk}) for i in ids]
        if rows:
            through.objects.bulk_create(rows, ignore_conflicts=True)


def backward(apps, schema_editor):
    Permission = apps.get_model("auth", "Permission")
    Permission.objects.filter(
        content_type__app_label="accounting", codename__in=list(FROM)
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0022_worker_folder"),
        ("oauth", "0020_rover_molyar_no_filer"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="operation",
            options={
                "ordering": ["-date", "-number"],
                "permissions": [
                    ("view_all_operations", "Barcha hamyonlar va amallarni ko'rish"),
                    ("view_finance_home", "Bosh sahifada moliya"),
                    ("view_finance_summary", "Moliya: Xulosa"),
                    ("view_finance_wallets", "Moliya: Hamyonlar"),
                    ("view_finance_orders", "Moliya: Buyurtmalar moliyasi"),
                    ("view_worker_card", "Moliya: Ishchi kartasi"),
                    ("view_advances", "Moliya: Avanslarni ko'rish"),
                    ("change_advances", "Moliya: Avanslarni tasdiqlash"),
                    ("view_finance_checks", "Moliya: Tekshiruv"),
                    ("view_order_bonus_line", "Moliya: Buyurtmadagi bonus"),
                ],
                "verbose_name": "Amal",
                "verbose_name_plural": "Amallar",
            },
        ),
        migrations.AlterModelOptions(
            name="debt",
            options={
                "ordering": ["-date", "-number"],
                "verbose_name": "Qarz",
                "verbose_name_plural": "Qarzlar",
            },
        ),
        migrations.RunPython(forward, backward),
    ]
