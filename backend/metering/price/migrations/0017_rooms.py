import django.db.models.deletion
from django.db import migrations, models

ROOMS = [
    ("Oshxona", "🍳"),
    ("Mehmonxona", "🛋"),
    ("Yotoqxona", "🛏"),
    ("Bolalar xonasi", "🧸"),
    ("Garderob", "👔"),
    ("Sanuzel", "🚿"),
    ("Prachka", "🧺"),
    ("Koridor / Xoll", "🚪"),
    ("Ofis", "💼"),
    ("Podval", "🎬"),
]


def seed_rooms(apps, schema_editor):
    RoomType = apps.get_model("price", "RoomType")
    for i, (name, icon) in enumerate(ROOMS):
        RoomType.objects.get_or_create(name=name, defaults={"icon": icon, "ordering": i})


class Migration(migrations.Migration):

    dependencies = [
        ("filer", "0017_image__transparent"),
        ("price", "0016_task_assignee"),
    ]

    operations = [
        migrations.AddField(
            model_name="price",
            name="client_title",
            field=models.CharField(
                blank=True, default="", max_length=255, verbose_name="Murojaat (PDF)"
            ),
        ),
        migrations.AddField(
            model_name="historicalprice",
            name="client_title",
            field=models.CharField(
                blank=True, default="", max_length=255, verbose_name="Murojaat (PDF)"
            ),
        ),
        migrations.AddField(
            model_name="price",
            name="variant",
            field=models.CharField(blank=True, default="", max_length=64, verbose_name="Variant"),
        ),
        migrations.AddField(
            model_name="historicalprice",
            name="variant",
            field=models.CharField(blank=True, default="", max_length=64, verbose_name="Variant"),
        ),
        migrations.CreateModel(
            name="RoomType",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("name", models.CharField(max_length=255, unique=True, verbose_name="Nomi")),
                (
                    "icon",
                    models.CharField(blank=True, default="", max_length=8, verbose_name="Belgi"),
                ),
                ("ordering", models.IntegerField(default=0, verbose_name="Tartib")),
                (
                    "object_types",
                    models.ManyToManyField(
                        blank=True,
                        related_name="room_types",
                        to="price.objecttype",
                        verbose_name="Mos mebellar",
                    ),
                ),
            ],
            options={
                "verbose_name": "Xona turi",
                "verbose_name_plural": "Xona turlari",
                "ordering": ["ordering", "name"],
            },
        ),
        migrations.CreateModel(
            name="Room",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("name", models.CharField(max_length=255, verbose_name="Nomi")),
                ("ordering", models.IntegerField(default=0, verbose_name="Tartib")),
                (
                    "price",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="rooms",
                        to="price.price",
                        verbose_name="Hisob-kitob",
                    ),
                ),
                (
                    "room_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="rooms",
                        to="price.roomtype",
                        verbose_name="Xona turi",
                    ),
                ),
            ],
            options={
                "verbose_name": "Xona",
                "verbose_name_plural": "Xonalar",
                "ordering": ["ordering", "id"],
            },
        ),
        migrations.CreateModel(
            name="RoomImage",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("ordering", models.IntegerField(default=0, verbose_name="Tartib")),
                (
                    "file",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="filer.image",
                        verbose_name="Rasm",
                    ),
                ),
                (
                    "room",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="images",
                        to="price.room",
                        verbose_name="Xona",
                    ),
                ),
            ],
            options={
                "verbose_name": "Xona rasmi",
                "verbose_name_plural": "Xona rasmlari",
                "ordering": ["ordering", "id"],
            },
        ),
        migrations.AddField(
            model_name="calculate",
            name="room",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="calculations",
                to="price.room",
                verbose_name="Xona",
            ),
        ),
        migrations.AddField(
            model_name="historicalcalculate",
            name="room",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to="price.room",
                verbose_name="Xona",
            ),
        ),
        migrations.AddField(
            model_name="calculate",
            name="note",
            field=models.TextField(blank=True, default="", verbose_name="Qo'shimcha"),
        ),
        migrations.AddField(
            model_name="historicalcalculate",
            name="note",
            field=models.TextField(blank=True, default="", verbose_name="Qo'shimcha"),
        ),
        migrations.RunPython(seed_rooms, migrations.RunPython.noop),
    ]
