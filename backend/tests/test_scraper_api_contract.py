from datetime import UTC, datetime
from uuid import uuid4

from marko.api.main import app
from marko.infrastructure.db.models import (
    PriceObservation,
    ScrapeHttpAttempt,
    ScrapeHttpRequest,
    ScrapeTarget,
    StoreSyncTaskExecution,
)
from marko.services.scraper_metrics import render_prometheus


def test_scraper_metrics_endpoints_are_in_openapi() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/jobs/{sync_run_id}/scrape-metrics" in paths
    assert "/api/v1/jobs/{sync_run_id}/scrape-metrics/prometheus" in paths
    assert "/api/v1/pricing/runs/{run_id}/collection-metrics" in paths
    assert (
        "/api/v1/pricing/runs/{run_id}/collection-metrics/prometheus"
        in paths
    )


def test_persistence_models_encode_three_work_levels_and_idempotency() -> None:
    assert ScrapeTarget.__table__.c.max_task_executions is not None
    assert StoreSyncTaskExecution.__table__.c.execution_no is not None
    assert ScrapeHttpRequest.__table__.c.request_key is not None
    assert ScrapeHttpAttempt.__table__.c.attempt_no is not None
    price_constraints = {
        constraint.name for constraint in PriceObservation.__table__.constraints
    }
    assert "uq_price_observation_sync_listing" in price_constraints


def test_prometheus_renderer_contains_every_required_metric_family() -> None:
    snapshot = {
        "generated_at": datetime.now(UTC),
        "scope_id": uuid4(),
        "item_kind": "store_sync",
        "item_version": "store-sync-v1",
        "item_lifecycle": {
            "scrape_items_submitted_total": 1,
            "scrape_items_valid_total": 1,
            "scrape_items_deduplicated_total": 0,
            "scrape_items_terminal_total": {"success": 1, "failed": 0},
            "scrape_items_inflight": {
                "queued": 0,
                "running": 0,
                "retry_wait": 0,
            },
        },
        "retry": {
            "http_attempts_per_request": 1.2,
            "http_attempts_per_item": 3.0,
        },
        "latency_seconds": {
            "request": {
                "catalog_page:success": {"p50": 1, "p95": 2, "p99": 3}
            },
            "task_runtime": {
                "succeeded": {"p50": 5, "p95": 5, "p99": 5}
            },
            "queue_wait": {"p50": 0.1, "p95": 0.2, "p99": 0.3},
            "end_to_end_item": {"p50": 5, "p95": 5, "p99": 5},
        },
        "requests": {
            "scrape_logical_requests_total": [
                {"request_kind": "catalog_page", "value": 2}
            ],
            "scrape_http_attempts_total": [
                {
                    "request_kind": "catalog_page",
                    "outcome": "success",
                    "status_class": "2xx",
                    "value": 2,
                }
            ],
            "scrape_http_request_rate": 0.5,
            "scrape_retry_backoff_seconds": 1,
        },
        "queue_workers": {
            "scrape_queue_depth": 0,
            "scrape_oldest_item_age_seconds": 0,
            "scrape_worker_slots": {"configured": 2, "busy": 0},
            "scrape_task_executions_total": [
                {"outcome": "succeeded", "value": 1}
            ],
            "scrape_task_redeliveries_total": 0,
            "scrape_worker_lost_total": 0,
        },
        "domain_output": {
            "scrape_catalog_pages_total": 2,
            "catalog_page_outcomes": {"success": 2},
            "scrape_products_extracted_total": 50,
            "scrape_products_persisted_total": 50,
            "scrape_duplicate_products_total": 0,
            "scrape_structured_completeness_ratio": 1,
            "scrape_evidence_coverage_ratio": 1,
            "scrape_raw_evidence_bytes_total": 1000,
            "scrape_database_writes_total": 120,
        },
        "resources_dependencies": {
            "process_cpu_utilization": 0.1,
            "process_resident_memory_bytes": 1024,
            "database_pool_in_use": 1,
            "database_probe_latency_seconds": 0.001,
            "database_transaction_latency_seconds": None,
            "broker_publish_latency_seconds": 0,
            "broker_consumer_lag": 0,
            "object_storage_write_latency_seconds": 0,
        },
    }

    output = render_prometheus(snapshot)
    required = {
        "scrape_items_submitted_total",
        "scrape_items_valid_total",
        "scrape_items_deduplicated_total",
        "scrape_items_terminal_total",
        "scrape_items_inflight",
        "scrape_item_latency_seconds",
        "scrape_logical_requests_total",
        "scrape_http_attempts_total",
        "scrape_http_attempts_per_request",
        "scrape_http_attempts_per_item",
        "scrape_http_request_latency_seconds",
        "scrape_http_request_rate",
        "scrape_retry_backoff_seconds",
        "scrape_queue_depth",
        "scrape_oldest_item_age_seconds",
        "scrape_worker_slots",
        "scrape_task_executions_total",
        "scrape_task_redeliveries_total",
        "scrape_worker_lost_total",
        "scrape_task_runtime_seconds",
        "scrape_catalog_pages_total",
        "scrape_products_extracted_total",
        "scrape_products_persisted_total",
        "scrape_duplicate_products_total",
        "scrape_structured_completeness_ratio",
        "scrape_evidence_coverage_ratio",
        "scrape_raw_evidence_bytes_total",
        "scrape_database_writes_total",
        "process_cpu_utilization",
        "process_resident_memory_bytes",
        "database_pool_in_use",
        "database_probe_latency_seconds",
        "database_transaction_latency_seconds",
        "broker_publish_latency_seconds",
        "broker_consumer_lag",
        "object_storage_write_latency_seconds",
    }
    emitted = {line.split("{", 1)[0] for line in output.splitlines()}

    assert required <= emitted
