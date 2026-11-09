from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("legislation", "0019_billdocument_source_purpose")]
    operations = [migrations.AddField(model_name="billcontract", name="reader_copy",
                                     field=models.JSONField(default=dict, blank=True))]
