from django.db import migrations


FALLBACK_TOPIC_SLUG = "general-legislation"


def assign_fallback_topics(apps, schema_editor):
    """Guarantee that historic bills are never left without a topic."""
    Bill = apps.get_model("legislation", "Bill")
    BillTopic = apps.get_model("legislation", "BillTopic")
    Topic = apps.get_model("legislation", "Topic")

    fallback_topic = Topic.objects.get(slug=FALLBACK_TOPIC_SLUG)
    existing_bill_ids = BillTopic.objects.values_list("bill_id", flat=True)
    missing_bill_ids = Bill.objects.exclude(pk__in=existing_bill_ids).values_list(
        "id", flat=True
    )
    BillTopic.objects.bulk_create(
        [
            BillTopic(
                bill_id=bill_id,
                topic_id=fallback_topic.id,
                confidence_score=0.0,
            )
            for bill_id in missing_bill_ids.iterator(chunk_size=1000)
        ],
        batch_size=1000,
        ignore_conflicts=True,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("legislation", "0011_seed_canonical_topics"),
    ]

    operations = [
        migrations.RunPython(assign_fallback_topics, migrations.RunPython.noop),
    ]
