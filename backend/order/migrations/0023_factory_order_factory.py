# Item 6: orders are now produced at a named Factory.
#
# order.factory is a required FK, so it's added nullable, back-filled to the
# DEFAULT_FACTORY_NAME factory ("Ser-mebel" — every order that existed before this
# change was made there), and only then made NOT NULL.

import django.db.models.deletion
import phonenumber_field.modelfields
from django.db import migrations, models

# Hardcoded on purpose: a migration is a frozen snapshot. The live value lives in
# order.constants.DEFAULT_FACTORY_NAME — if that is ever renamed, this literal must
# stay as it is so replaying 0023 keeps producing the factory production actually has.
DEFAULT_FACTORY_NAME = "Ser-mebel"


def create_default_factory_and_backfill(apps, schema_editor):
    db = schema_editor.connection.alias
    Factory = apps.get_model("order", "Factory")
    Order = apps.get_model("order", "Order")
    HistoricalOrder = apps.get_model("order", "HistoricalOrder")

    factory, _ = Factory.objects.using(db).get_or_create(name=DEFAULT_FACTORY_NAME)
    Order.objects.using(db).filter(factory__isnull=True).update(factory=factory)
    HistoricalOrder.objects.using(db).filter(factory__isnull=True).update(factory=factory)


def drop_default_factory(apps, schema_editor):
    """Reverse: only safe once no order points at it, hence the guard."""
    db = schema_editor.connection.alias
    Factory = apps.get_model("order", "Factory")
    Order = apps.get_model("order", "Order")

    if not Order.objects.using(db).filter(factory__name=DEFAULT_FACTORY_NAME).exists():
        Factory.objects.using(db).filter(name=DEFAULT_FACTORY_NAME).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("order", "0022_remove_historicalorder_count_days_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="Factory",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("name", models.CharField(max_length=255, unique=True, verbose_name="Название")),
                (
                    "address",
                    models.CharField(
                        blank=True, default="", max_length=255, verbose_name="Адрес"
                    ),
                ),
                (
                    "phone",
                    phonenumber_field.modelfields.PhoneNumberField(
                        blank=True, max_length=128, region="UZ", verbose_name="Телефон"
                    ),
                ),
                ("ordering", models.IntegerField(default=0, verbose_name="Порядковый номер")),
            ],
            options={
                "verbose_name": "Завод",
                "verbose_name_plural": "Заводы",
                "ordering": ["ordering", "name"],
            },
        ),
        migrations.AddField(
            model_name="historicalorder",
            name="factory",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="order.factory",
                verbose_name="Завод",
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="factory",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                to="order.factory",
                verbose_name="Завод",
            ),
        ),
        migrations.RunPython(create_default_factory_and_backfill, drop_default_factory),
        migrations.AlterField(
            model_name="order",
            name="factory",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                to="order.factory",
                verbose_name="Завод",
            ),
        ),
    ]
