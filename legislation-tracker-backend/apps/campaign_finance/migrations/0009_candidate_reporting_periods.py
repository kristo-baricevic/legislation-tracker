from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("campaign_finance", "0008_outside_spending")]
    operations = [migrations.AddField(model_name="candidateidentity", name="reporting_periods", field=models.JSONField(default=dict))]
