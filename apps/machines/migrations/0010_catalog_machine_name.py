from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("machines", "0009_catalog_job_card_format"),
    ]

    operations = [
        migrations.AddField(
            model_name="planningcatalogitem",
            name="machine_name",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                help_text="Short machine name from Excel column machine NAME (e.g. ML37IE-A7.5).",
                max_length=160,
            ),
        ),
        migrations.AddField(
            model_name="machineplanningdata",
            name="machine_name",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                help_text="Short name from Model Catalog (Excel machine NAME column).",
                max_length=160,
            ),
        ),
    ]
