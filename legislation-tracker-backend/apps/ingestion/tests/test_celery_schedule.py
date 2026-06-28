def test_celery_beat_schedules_tracked_bill_polling():
    from config.celery import app

    schedule = app.conf.beat_schedule

    assert schedule["poll-tracked-bills"]["task"] == (
        "apps.ingestion.tasks.poll_tracked_bills"
    )
    assert schedule["poll-tracked-bills"]["schedule"] == 300.0
