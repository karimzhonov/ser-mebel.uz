import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("accounting", "0025_backfill_debt_allocations"),
        ("order", "0025_backfill_location"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SalarySheet",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("number", models.PositiveIntegerField(unique=True, verbose_name="№")),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("oddiy", "Oddiy oylik (fiksa)"),
                            ("sborka", "Sborka / ishbay (buyurtmalar bo'yicha)"),
                            ("ofis", "Ofis xodimi (oklad + bonus)"),
                            ("menejer", "Menejer (fiksa + bonus)"),
                            ("sotuv", "Sotuv (fiksa + bonuslar)"),
                            ("zamer", "Zamer (fiksa + bonuslar)"),
                        ],
                        max_length=16,
                        verbose_name="Turi",
                    ),
                ),
                ("section", models.CharField(blank=True, default="", max_length=128, verbose_name="Soha / bo'lim")),
                ("position", models.CharField(blank=True, default="", max_length=128, verbose_name="Lavozim")),
                ("month", models.DateField(db_index=True, verbose_name="Oy")),
                ("period_start", models.DateField(verbose_name="Davr boshi")),
                ("period_end", models.DateField(verbose_name="Davr oxiri")),
                ("usd_rate", models.DecimalField(decimal_places=4, max_digits=16, verbose_name="USD kursi")),
                ("fixed", models.DecimalField(decimal_places=2, default=0, max_digits=16, verbose_name="Fiksa / oklad (so'm)")),
                ("bonus_percent", models.DecimalField(decimal_places=4, default=0, max_digits=7, verbose_name="Olingan zakaz bonusi (%)")),
                ("bonus2_percent", models.DecimalField(decimal_places=4, default=0, max_digits=7, verbose_name="Topshirilgan zakaz bonusi (%)")),
                ("late_days", models.PositiveSmallIntegerField(default=0, verbose_name="Kech qolgan kunlar")),
                ("late_rate", models.DecimalField(decimal_places=2, default=0, max_digits=16, verbose_name="Bir kunlik shtraf (so'm)")),
                ("late_dates", models.CharField(blank=True, default="", max_length=255, verbose_name="Sanalar")),
                ("absent_days", models.PositiveSmallIntegerField(default=0, verbose_name="Kelmagan kunlar")),
                ("absent_rate", models.DecimalField(decimal_places=2, default=0, max_digits=16, verbose_name="Bir kun uchun (so'm)")),
                ("absent_dates", models.CharField(blank=True, default="", max_length=255, verbose_name="Sanalar")),
                ("instagram_count", models.PositiveIntegerField(default=0, verbose_name="Instagram istoriyalar soni")),
                ("note", models.TextField(blank=True, default="", verbose_name="Izoh")),
                (
                    "status",
                    models.CharField(
                        choices=[("draft", "Qoralama"), ("submitted", "Tasdiqlashda"), ("approved", "Tasdiqlangan")],
                        db_index=True,
                        default="draft",
                        max_length=16,
                        verbose_name="Holat",
                    ),
                ),
                ("version", models.PositiveIntegerField(default=0)),
                ("returned_note", models.CharField(blank=True, default="", max_length=500, verbose_name="Qaytarish sababi")),
                ("totals", models.JSONField(blank=True, default=dict)),
                ("snapshot", models.JSONField(blank=True, null=True)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "worker",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="salary_sheets",
                        to="accounting.worker",
                        verbose_name="Xodim",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+", to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+", to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "submitted_by",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+", to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "approved_by",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+", to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "Oylik varaqasi",
                "verbose_name_plural": "Oylik varaqlari",
                "ordering": ["-month", "-number"],
                "permissions": [("approve_salarysheet", "Oylik varaqasini tasdiqlash")],
                "indexes": [models.Index(fields=["worker", "month"], name="salarysheet_worker_month")],
            },
        ),
        migrations.CreateModel(
            name="SheetMember",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("share", models.DecimalField(decimal_places=4, max_digits=7, verbose_name="Ulush (%)")),
                ("position", models.PositiveSmallIntegerField(default=0)),
                (
                    "sheet",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="members",
                        to="payroll.salarysheet",
                    ),
                ),
                (
                    "worker",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="accounting.worker",
                    ),
                ),
            ],
            options={
                "ordering": ["position", "id"],
                "constraints": [models.UniqueConstraint(fields=("sheet", "worker"), name="uniq_sheet_member")],
            },
        ),
        migrations.CreateModel(
            name="SheetLine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "section",
                    models.CharField(
                        choices=[
                            ("job", "Bajarilgan ish (so'm)"),
                            ("taken", "Olingan zakaz ($)"),
                            ("delivered", "Topshirilgan zakaz ($)"),
                            ("collect", "Pul yechish bonusi"),
                            ("deduction", "Ushlanma"),
                            ("car", "Mashina puli"),
                        ],
                        max_length=16,
                    ),
                ),
                ("position", models.PositiveSmallIntegerField(default=0)),
                ("order_ref", models.CharField(blank=True, db_index=True, default="", max_length=32)),
                ("title", models.CharField(blank=True, default="", max_length=255, verbose_name="Mijoz / izoh")),
                ("on_date", models.DateField(blank=True, null=True)),
                ("paid_on", models.DateField(blank=True, null=True)),
                ("currency", models.CharField(default="UZS", max_length=3)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=16)),
                ("rate", models.DecimalField(blank=True, decimal_places=4, max_digits=16, null=True)),
                (
                    "order",
                    models.ForeignKey(
                        blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+", to="order.order",
                    ),
                ),
                (
                    "sheet",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="payroll.salarysheet",
                    ),
                ),
            ],
            options={"ordering": ["section", "position", "id"]},
        ),
    ]
