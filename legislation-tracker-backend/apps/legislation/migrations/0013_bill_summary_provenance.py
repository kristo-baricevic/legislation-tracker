from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("legislation", "0012_assign_fallback_topics_to_existing_bills"),
    ]

    operations = [
        migrations.AddField(
            model_name="bill",
            name="summary_source",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.AddField(
            model_name="bill",
            name="summary_action_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="bill",
            name="summary_version_code",
            field=models.CharField(blank=True, default="", max_length=16),
        ),
        migrations.AddField(
            model_name="bill",
            name="summary_last_updated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
