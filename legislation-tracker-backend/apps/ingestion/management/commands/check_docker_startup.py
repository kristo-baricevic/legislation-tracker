"""Fail early instead of starting a frontend with disabled ingestion."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.llm_credentials import llm_feature_configuration_errors


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("--initialize-storage", action="store_true")

    def handle(self, *args, **options):
        missing = [
            name
            for name in ("CONGRESS_API_KEY", "FEC_API_KEY")
            if not str(getattr(settings, name, "")).strip()
        ]
        if missing:
            raise CommandError("Missing required configuration: " + ", ".join(missing))
        errors = llm_feature_configuration_errors(production=False)
        if errors:
            raise CommandError("Enhancement configuration: " + ", ".join(errors))
        if not settings.LLM_ENHANCEMENTS_ENABLED:
            self.stdout.write(
                "Enhancements explicitly disabled; restore the original encryption keys to enable them."
            )
        if options["initialize_storage"]:
            import boto3
            from botocore.exceptions import ClientError

            storage = boto3.client(
                "s3",
                endpoint_url=settings.AWS_S3_ENDPOINT_URL,
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            )
            bucket = settings.AWS_STORAGE_BUCKET_NAME
            try:
                storage.head_bucket(Bucket=bucket)
            except ClientError as exc:
                if exc.response["Error"]["Code"] not in ("404", "NoSuchBucket"):
                    raise CommandError("Document storage is not accessible") from exc
                storage.create_bucket(Bucket=bucket)
        self.stdout.write(self.style.SUCCESS("Docker configuration ready."))
