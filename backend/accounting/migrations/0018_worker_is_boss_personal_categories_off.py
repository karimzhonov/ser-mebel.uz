from django.db import migrations, models


def forward(apps, schema_editor):
    Worker = apps.get_model("accounting", "Worker")
    FinanceCategory = apps.get_model("accounting", "FinanceCategory")
    # the boss's salary row the owner added («Mirmuxammad — rahbar»)
    Worker.objects.filter(position__icontains="rahbar").update(is_boss=True)
    # owner's rule: the boss's wallet is the company cash — no personal expenses in it
    # any more (old rows keep their category, they just can't be booked again)
    FinanceCategory.objects.filter(code__in=["uy", "rahbarga"]).update(is_active=False)


def backward(apps, schema_editor):
    FinanceCategory = apps.get_model("accounting", "FinanceCategory")
    FinanceCategory.objects.filter(code__in=["uy", "rahbarga"]).update(is_active=True)


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0017_worker_salary"),
    ]

    operations = [
        migrations.AddField(
            model_name="worker",
            name="is_boss",
            field=models.BooleanField(default=False, verbose_name="Rahbar"),
        ),
        migrations.AlterField(
            model_name="operation",
            name="pay_type",
            field=models.CharField(
                blank=True,
                choices=[("Avans", "Avans"), ("Oylik", "Oylik"), ("Uy uchun", "Uy uchun")],
                default="",
                max_length=16,
                verbose_name="Ish haqi turi",
            ),
        ),
        migrations.RunPython(forward, backward),
    ]
