from django.db import migrations


def seed_canonical_topics(apps, schema_editor):
    from apps.legislation.topic_taxonomy import seed_topic_taxonomy

    seed_topic_taxonomy(apps.get_model("legislation", "Topic"))


class Migration(migrations.Migration):
    dependencies = [
        ("legislation", "0010_billdocument_source_order"),
    ]

    operations = [
        migrations.RunPython(seed_canonical_topics, migrations.RunPython.noop),
    ]
