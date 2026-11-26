"""Stage 3: overhead (umumiy xarajat) shared over the orders and «Foyda yechish».

* FinanceCar.is_overhead — the owner's company cars (Labo — Elyor, Shineray — Ulug'bek,
  Jumaka) are flagged here; their costs become overhead (accounting/overhead.py).
* OrderOverhead — an order's share, fixed on its Готов day.
* the «💰 Foyda yechish» category: money the boss takes out of the profit; excluded, so
  it is neither a company expense nor an order cost.
* FinanceCategory.members — only these wallets may book the category (empty = all).
* the «📦 Omborga xarid» category: stock bought for the warehouse; excluded and without
  an order — it reaches a client only when given out of the warehouse.
* the permission «Moliya: Foyda yechish» (superusers have it; give it to the boss's
  group on the site if needed)."""

from django.db import migrations, models

COMPANY_CARS = ("Labo — Elyor", "Shineray — Ulug'bek", "Jumaka")


def forward(apps, schema_editor):
    Car = apps.get_model("accounting", "FinanceCar")
    Car.objects.filter(name__in=COMPANY_CARS).update(is_overhead=True)
    Category = apps.get_model("accounting", "FinanceCategory")
    Category.objects.get_or_create(
        code="foyda",
        defaults=dict(
            kind="expense",
            emoji="💰",
            name="Foyda yechish",
            keywords=[],
            color="#16A34A",
            ordering=999,
            is_active=True,
            no_order=True,
            admin_only=True,
            excluded=True,
        ),
    )
    # owner's rule: stock bought for the warehouse leaves the wallet, but is a client's
    # cost only when it is given out of the warehouse (warehouse chiqim → «spent»), so
    # the purchase is neither overhead nor any order's cost
    Category.objects.get_or_create(
        code="omborga",
        defaults=dict(
            kind="expense",
            emoji="📦",
            name="Omborga xarid",
            keywords=["ombor", "omborga", "склад", "sklad"],
            color="#8D6E63",
            ordering=998,
            is_active=True,
            no_order=True,
            admin_only=False,
            excluded=True,
        ),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0025_backfill_debt_allocations"),
        ("oauth", "0020_rover_molyar_no_filer"),
    ]

    operations = [
        migrations.AddField(
            model_name="financecategory",
            name="members",
            field=models.ManyToManyField(
                blank=True,
                related_name="allowed_categories",
                to="oauth.telegrammember",
                verbose_name="Faqat shu hamyonlar",
            ),
        ),
        migrations.AddField(
            model_name="financecar",
            name="is_overhead",
            field=models.BooleanField(default=False, verbose_name="O'zgarmas xarajat"),
        ),
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
                    ("withdraw_profit", "Moliya: Foyda yechish"),
                ],
                "verbose_name": "Amal",
                "verbose_name_plural": "Amallar",
            },
        ),
        migrations.CreateModel(
            name="OrderOverhead",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "order_ref",
                    models.CharField(max_length=32, unique=True, verbose_name="Buyurtma ID"),
                ),
                ("ready_date", models.DateField(db_index=True, verbose_name="Готов sanasi")),
                (
                    "base",
                    models.DecimalField(
                        decimal_places=2, max_digits=16, verbose_name="Shartnoma (so'm)"
                    ),
                ),
                (
                    "rate",
                    models.DecimalField(
                        decimal_places=6, max_digits=9, verbose_name="Stavka (ulush)"
                    ),
                ),
                (
                    "amount",
                    models.DecimalField(
                        decimal_places=2, max_digits=16, verbose_name="Ulush (so'm)"
                    ),
                ),
                ("window_start", models.DateField(verbose_name="Stavka davri boshi")),
                ("window_end", models.DateField(verbose_name="Stavka davri oxiri")),
                (
                    "overhead_total",
                    models.DecimalField(decimal_places=2, default=0, max_digits=16),
                ),
                ("sales_total", models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Buyurtmaning umumiy xarajat ulushi",
                "verbose_name_plural": "Buyurtmalarning umumiy xarajat ulushlari",
                "ordering": ["-ready_date", "order_ref"],
            },
        ),
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
