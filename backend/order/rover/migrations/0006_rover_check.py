import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rover", "0005_alter_historicalrover_options_alter_rover_options"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="historicalrover",
            name="checked_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Tasdiqlangan"),
        ),
        migrations.AddField(
            model_name="historicalrover",
            name="submitted_at",
            field=models.DateTimeField(
                blank=True, null=True, verbose_name="Tekshiruvga yuborilgan"
            ),
        ),
        migrations.AddField(
            model_name="historicalrover",
            name="checked_by",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="historicalrover",
            name="submitted_by",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="rover",
            name="checked_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Tasdiqlangan"),
        ),
        migrations.AddField(
            model_name="rover",
            name="submitted_at",
            field=models.DateTimeField(
                blank=True, null=True, verbose_name="Tekshiruvga yuborilgan"
            ),
        ),
        migrations.AddField(
            model_name="rover",
            name="checked_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="rover",
            name="submitted_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
