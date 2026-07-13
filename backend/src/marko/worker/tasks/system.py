"""Small task used to verify broker/worker connectivity."""
from __future__ import annotations

from marko.worker.celery_app import celery_app


@celery_app.task(name="marko.worker.healthcheck")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}

