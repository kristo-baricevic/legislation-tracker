from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("changelog", "0004_bill_activity_clock")]

    operations = [
        migrations.AddIndex(
            model_name="changelog",
            index=models.Index(
                fields=["bill", "created_at", "id"],
                name="changelog_bill_cursor_idx",
            ),
        )
    ]
