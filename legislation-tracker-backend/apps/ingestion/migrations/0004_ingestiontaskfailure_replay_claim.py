from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ingestion", "0003_ingestionworkitem_and_failure_replay"),
    ]

    operations = [
        migrations.AddField(
            model_name="ingestiontaskfailure",
            name="replay_claim_token",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.AddField(
            model_name="ingestiontaskfailure",
            name="replay_claim_expires_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
