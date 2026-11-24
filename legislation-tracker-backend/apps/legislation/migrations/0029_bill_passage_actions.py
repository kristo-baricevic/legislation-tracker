from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("legislation", "0028_reader_budget_pause")]
    operations = [migrations.AddField(model_name="bill", name="passage_actions", field=models.JSONField(default=list, blank=True))]
