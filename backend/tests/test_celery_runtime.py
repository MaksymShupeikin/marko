"""Celery delivery semantics required by worker-loss recovery."""

from marko.worker.celery_app import celery_app, settings


def test_redis_visibility_timeout_is_explicit_and_consistent() -> None:
    expected = settings.celery_visibility_timeout_seconds

    assert expected > 0
    assert celery_app.conf.broker_transport_options["visibility_timeout"] == expected
    assert (
        celery_app.conf.result_backend_transport_options["visibility_timeout"]
        == expected
    )
    assert celery_app.conf.visibility_timeout == expected
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True
