from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("legislation", "0009_billsearchchunk"),
    ]

    operations = [
        migrations.AddField(
            model_name="billdocument",
            name="source_order",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
