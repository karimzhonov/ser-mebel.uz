from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("hr", "0002_drop_await_state"),
    ]

    operations = [
        migrations.AddField(
            model_name="employee",
            name="birth_date",
            field=models.DateField(blank=True, null=True, verbose_name="Tug'ilgan kun"),
        ),
    ]
