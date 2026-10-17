from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('legislation', '0014_billenhancementattempt_failure_detail')]
    operations = [migrations.AddField(
        model_name='billenhancementattempt', name='citation_resolution_json',
        field=models.JSONField(default=dict, blank=True),
    )]
