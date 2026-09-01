import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0006_llmcredential")]

    operations = [
        migrations.CreateModel(
            name="SavedBillSearch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("query_json", models.JSONField(default=dict)),
                ("normalized_hash", models.CharField(max_length=64)),
                ("last_opened_at", models.DateTimeField(blank=True, null=True)),
                ("last_opened_activity_sequence", models.BigIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="saved_bill_searches", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "accounts_savedbillsearch"},
        ),
        migrations.AddConstraint(
            model_name="savedbillsearch",
            constraint=models.UniqueConstraint(fields=("user", "name"), name="accounts_saved_search_user_name_uniq"),
        ),
        migrations.AddConstraint(
            model_name="savedbillsearch",
            constraint=models.UniqueConstraint(fields=("user", "normalized_hash"), name="accounts_saved_search_user_query_uniq"),
        ),
        migrations.AddIndex(
            model_name="savedbillsearch",
            index=models.Index(fields=["user", "updated_at"], name="accounts_sa_user_id_28b69d_idx"),
        ),
    ]
