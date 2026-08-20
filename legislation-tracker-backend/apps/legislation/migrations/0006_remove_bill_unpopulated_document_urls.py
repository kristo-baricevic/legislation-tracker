from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("legislation", "0005_contract_and_topic_uniqueness"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="bill",
            name="raw_text_url",
        ),
        migrations.RemoveField(
            model_name="bill",
            name="pdf_url",
        ),
    ]
