from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("legislation", "0017_source_first_retry_identity")]

    operations = [
        migrations.AlterField(
            model_name="bill",
            name="status",
            field=models.TextField(),
        ),
    ]
