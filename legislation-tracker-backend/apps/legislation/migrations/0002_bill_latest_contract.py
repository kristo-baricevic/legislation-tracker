# Generated manually for Phase 2

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("legislation", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="bill",
            name="latest_contract",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="legislation.billcontract",
            ),
        ),
    ]
