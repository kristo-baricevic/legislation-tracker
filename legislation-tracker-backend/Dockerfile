FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY requirements/production.lock requirements/production.lock
RUN pip install --upgrade pip && pip install --require-hashes -r requirements/production.lock

COPY . .
RUN python manage.py collectstatic --noinput \
    && mkdir -p /app/local_media \
    && chown -R app:app /app

USER app

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-", "--error-logfile", "-"]
