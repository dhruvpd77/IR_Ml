from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("machines", "0008_model_wise_job_cards"),
    ]

    operations = [
        migrations.AddField(
            model_name="planningcatalogitem",
            name="job_card_format",
            field=models.CharField(
                blank=True,
                db_index=True,
                default="",
                help_text="excel = Production Checklists workbook; word = file in jobcard_word_file/.",
                max_length=16,
            ),
        ),
    ]
