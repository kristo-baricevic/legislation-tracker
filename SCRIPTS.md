celery -A config worker -l info
celery -A config beat -l info

python -m venv .venv
source .venv/bin/activate
pip install -r requirements/dev.txt
pip install -r requirements/base.txt
python manage.py migrate

python manage.py shell -c "from apps.ingestion.tasks import poll_congress; print(poll_congress.delay().get(timeout=30))"

export DJANGO_SETTINGS_MODULE=config.settings.dev
