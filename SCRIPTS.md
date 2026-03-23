celery -A config worker -l info
celery -A config beat -l info

python -m venv .venv
source .venv/bin/activate
pip install -r requirements/dev.txt
pip install -r requirements/base.txt
python manage.py migrate

# Enqueue poll_congress (one line only — avoid indented multi-line strings in `-c` or you get IndentationError)
# Now paginates the API (250 per page) until all bills in that query are enqueued.
python manage.py shell -c "from apps.ingestion.tasks import poll_congress; r=poll_congress.delay(); print(r.get(timeout=600))"

# Download bill text for EVERY bill already in Postgres (e.g. session 119). Spawns many Celery tasks — watch API rate limits.
python manage.py shell -c "from apps.ingestion.tasks import backfill_process_bill_versions_for_all_bills; print(backfill_process_bill_versions_for_all_bills.delay(session=119).get(timeout=60))"

# Reset incremental poll cursor so the NEXT poll asks Congress for the full list again (not just “since last update”):
# python manage.py shell -c "from apps.ingestion.models import IngestionState; print(IngestionState.objects.filter(jurisdiction='federal', congress=119).update(last_bill_update_seen_at=None))"

export DJANGO_SETTINGS_MODULE=config.settings.dev
