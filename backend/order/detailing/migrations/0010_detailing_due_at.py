from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("detailing", "0009_remove_detailing_pointer_type_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="detailing",
            name="due_at",
            field=models.DateTimeField(
                blank=True, db_index=True, null=True, verbose_name="Срок деталировки"
            ),
        ),
        migrations.AddField(
            model_name="historicaldetailing",
            name="due_at",
            field=models.DateTimeField(
                blank=True, db_index=True, null=True, verbose_name="Срок деталировки"
            ),
        ),
    ]
