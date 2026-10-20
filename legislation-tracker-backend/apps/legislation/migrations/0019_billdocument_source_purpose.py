from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("legislation", "0018_bill_full_action_text")]
    operations = [
        migrations.AddField(
            model_name="billdocument",
            name="source_purpose",
            field=models.TextField(blank=True, default=""),
        ),
    ]
