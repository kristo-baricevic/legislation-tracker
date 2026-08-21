def test_celery_beat_schedules_tracked_bill_polling():
    from config.celery import app

    schedule = app.conf.beat_schedule

    assert schedule["poll-tracked-bills"]["task"] == (
        "apps.ingestion.tasks.poll_tracked_bills"
    )
    assert schedule["poll-tracked-bills"]["schedule"] == 300.0


def test_celery_beat_recomputes_similarity_for_the_entire_session():
    from config.celery import app

    schedule = app.conf.beat_schedule

    assert schedule["recompute-similarity-batch"]["kwargs"] == {"session": 119}


def test_celery_beat_dispatches_and_recovers_durable_ingestion_work():
    from config.celery import app

    schedule = app.conf.beat_schedule

    assert schedule["dispatch-ingestion-work"] == {
        "task": "apps.ingestion.tasks.dispatch_ingestion_work",
        "schedule": 30.0,
    }
    assert schedule["recover-stale-ingestion-work"] == {
        "task": "apps.ingestion.tasks.recover_stale_ingestion_work",
        "schedule": 300.0,
    }


def test_celery_requeues_late_acked_tasks_when_a_worker_process_is_lost():
    from config.celery import app

    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is True


def test_celery_beat_syncs_the_full_current_representative_roster_daily():
    from config.celery import app

    assert app.conf.beat_schedule["sync-representatives"] == {
        "task": "apps.ingestion.tasks.sync_representatives",
        "schedule": 86400.0,
        "kwargs": {"congress": 119},
    }


def test_celery_beat_maintains_future_changelog_partitions_daily():
    from config.celery import app

    assert app.conf.beat_schedule["ensure-changelog-partitions"] == {
        "task": "apps.changelog.tasks.ensure_change_log_partitions_task",
        "schedule": 86400.0,
        "kwargs": {"months_ahead": 12},
    }


def test_task_failure_handler_records_legislation_task_failures(monkeypatch):
    from apps.ingestion import tasks
    from config.celery import _on_task_failure

    recorded = []
    monkeypatch.setattr(
        tasks,
        "_record_task_failure",
        lambda task_id, task_name, args, kwargs, bill_id, exc: recorded.append(
            (task_id, task_name, args, kwargs, bill_id, str(exc))
        ),
    )

    sender = type("Sender", (), {"name": "apps.legislation.tasks.generate_contract"})()
    _on_task_failure(
        sender=sender,
        task_id="failed-task",
        exception=RuntimeError("contract failed"),
        args=(23,),
        kwargs={},
    )

    assert recorded == [
        (
            "failed-task",
            "apps.legislation.tasks.generate_contract",
            (23,),
            {},
            None,
            "contract failed",
        )
    ]


def test_task_failure_handler_records_changelog_maintenance_failures(monkeypatch):
    from apps.ingestion import tasks
    from config.celery import _on_task_failure

    recorded = []
    monkeypatch.setattr(
        tasks,
        "_record_task_failure",
        lambda task_id, task_name, args, kwargs, bill_id, exc: recorded.append(
            (task_id, task_name, args, kwargs, bill_id, str(exc))
        ),
    )

    sender = type(
        "Sender", (), {"name": "apps.changelog.tasks.ensure_change_log_partitions_task"}
    )()
    _on_task_failure(
        sender=sender,
        task_id="failed-maintenance",
        exception=RuntimeError("partition maintenance failed"),
        args=(),
        kwargs={"months_ahead": 12},
    )

    assert recorded == [
        (
            "failed-maintenance",
            "apps.changelog.tasks.ensure_change_log_partitions_task",
            (),
            {"months_ahead": 12},
            None,
            "partition maintenance failed",
        )
    ]
