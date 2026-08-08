"""Celery application shared by workers and scheduler."""

from __future__ import annotations

from celery import Celery

from marko.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "marko",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "marko.worker.tasks.import_store",
        "marko.worker.tasks.fitment",
        "marko.worker.tasks.pricing",
        "marko.worker.tasks.system",
    ],
)
celery_app.conf.update(
    broker_transport_options={
        "visibility_timeout": settings.celery_visibility_timeout_seconds,
    },
    result_backend_transport_options={
        "visibility_timeout": settings.celery_visibility_timeout_seconds,
    },
    visibility_timeout=settings.celery_visibility_timeout_seconds,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    timezone="UTC",
    task_routes={
        "marko.worker.import_store_catalog": {"queue": "store-sync"},
        "marko.worker.process_pricing_item": {"queue": "pricing"},
        "marko.worker.calculate_pricing_item": {"queue": "pricing-calculation"},
        "marko.worker.finalize_pricing_collection": {"queue": "celery"},
        "marko.worker.start_pricing_run": {"queue": "celery"},
        "marko.worker.re_enrich_market_observations": {"queue": "celery"},
        "marko.worker.process_ai_evidence_position": {
            "queue": "pricing-calculation"
        },
        "marko.worker.cleanup_scrape_evidence": {"queue": "celery"},
        "marko.worker.reconcile_scrape_outbox": {"queue": "celery"},
        "marko.worker.reconcile_stale_workflows": {"queue": "celery"},
        "marko.worker.schedule_store_monitoring": {"queue": "celery"},
        "marko.worker.process_fitment_analysis": {"queue": "celery"},
    },
    beat_schedule={
        "cleanup-orphaned-scrape-evidence": {
            "task": "marko.worker.cleanup_scrape_evidence",
            "schedule": max(60, settings.scrape_evidence_gc_interval_seconds),
        },
        "reconcile-scrape-dispatch-outbox": {
            "task": "marko.worker.reconcile_scrape_outbox",
            "schedule": max(5, settings.scrape_outbox_reconcile_interval_seconds),
        },
        "reconcile-stale-workflows": {
            "task": "marko.worker.reconcile_stale_workflows",
            "schedule": max(15, settings.workflow_reconcile_interval_seconds),
        },
        "schedule-store-monitoring": {
            "task": "marko.worker.schedule_store_monitoring",
            "schedule": max(60, settings.store_monitoring_scan_interval_seconds),
        },
    },
)
