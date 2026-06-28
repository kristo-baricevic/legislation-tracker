"""
Management command to seed the Topic table from the canonical taxonomy.

Usage:
    python manage.py seed_topics          # create missing topics
    python manage.py seed_topics --reset  # delete all topics + BillTopics, re-create
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.legislation.models import BillTopic, Topic
from apps.legislation.topic_taxonomy import TOPICS


class Command(BaseCommand):
    help = "Seed Topic table from the canonical taxonomy in topic_taxonomy.py"

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete all existing topics and BillTopics before seeding.",
        )

    def handle(self, *args, **options):
        if options["reset"]:
            with transaction.atomic():
                bt_count = BillTopic.objects.count()
                BillTopic.objects.all().delete()
                t_count = Topic.objects.count()
                Topic.objects.all().delete()
            self.stdout.write(
                f"Deleted {t_count} topics and {bt_count} bill-topic links."
            )

        created = 0
        updated = 0
        for entry in TOPICS:
            topic, was_created = Topic.objects.update_or_create(
                slug=entry["slug"],
                defaults={
                    "name": entry["name"],
                    "description": entry["description"],
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {created} created, {updated} updated "
                f"({Topic.objects.count()} total topics)."
            )
        )
