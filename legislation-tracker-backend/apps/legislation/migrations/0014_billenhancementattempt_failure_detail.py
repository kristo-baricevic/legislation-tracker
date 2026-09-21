from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("legislation", "0013_bill_summary_provenance")]

    operations = [
        migrations.AddField(
            model_name="billenhancementattempt",
            name="failure_detail",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
