from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("congress", "0004_voterecord_uniqueness"),
    ]

    operations = [
        migrations.AddField(
            model_name="representative",
            name="first_name",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="representative",
            name="last_name",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="representative",
            name="official_website_url",
            field=models.URLField(blank=True, max_length=1024, null=True),
        ),
        migrations.AddField(
            model_name="representative",
            name="image_url",
            field=models.URLField(blank=True, max_length=1024, null=True),
        ),
        migrations.AddField(
            model_name="representative",
            name="source_api_url",
            field=models.URLField(blank=True, max_length=1024, null=True),
        ),
        migrations.AddField(
            model_name="representative",
            name="last_seen_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
