import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0018_worker_is_boss_personal_categories_off"),
    ]

    operations = [
        migrations.CreateModel(
            name="OperationChange",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("edit", "Tahrirlandi"),
                            ("delete", "O'chirildi"),
                            ("restore", "Tiklandi"),
                        ],
                        max_length=16,
                    ),
                ),
                ("at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("by_name", models.CharField(blank=True, default="", max_length=255)),
                ("via", models.CharField(blank=True, default="", max_length=8)),
                ("changes", models.JSONField(blank=True, default=dict)),
                (
                    "by_member",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="oauth.telegrammember",
                    ),
                ),
                (
                    "by_user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="oauth.user",
                    ),
                ),
                (
                    "operation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="changes",
                        to="accounting.operation",
                    ),
                ),
            ],
            options={
                "verbose_name": "Amal o'zgarishi",
                "verbose_name_plural": "Amallar o'zgarishlari",
                "ordering": ["-at", "-id"],
            },
        ),
    ]
