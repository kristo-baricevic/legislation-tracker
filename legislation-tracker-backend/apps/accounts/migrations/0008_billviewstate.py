import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0007_savedbillsearch"),
        ("legislation", "0009_billsearchchunk"),
    ]

    operations = [
        migrations.CreateModel(
            name="BillViewState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("last_viewed_at", models.DateTimeField(blank=True, null=True)),
                ("last_seen_change_created_at", models.DateTimeField(blank=True, null=True)),
                ("last_seen_change_id", models.BigIntegerField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("bill", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="view_states", to="legislation.bill")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="bill_view_states", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "accounts_billviewstate"},
        ),
        migrations.AddConstraint(
            model_name="billviewstate",
            constraint=models.UniqueConstraint(fields=("user", "bill"), name="accounts_bill_view_state_user_bill_uniq"),
        ),
        migrations.AddIndex(
            model_name="billviewstate",
            index=models.Index(fields=["user", "updated_at"], name="accounts_bi_user_id_3b140a_idx"),
        ),
    ]
