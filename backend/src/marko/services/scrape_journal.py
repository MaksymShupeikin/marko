"""Durable persistence and replay access for scraper HTTP traces."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import zlib
from uuid import UUID, uuid4

from sqlalchemy import delete, exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from marko.infrastructure.db.models import (
    ScrapeEvidenceBlob,
    ScrapeHttpAttempt,
    ScrapeHttpRequest,
)
from marko.services.scrape_runtime import LogicalRequestTrace, ReplayEvidence


class EvidenceIntegrityError(RuntimeError):
    """Content-addressed raw evidence failed an integrity check."""


@dataclass(frozen=True)
class TracePersistenceStats:
    logical_requests: int
    physical_attempts: int
    catalog_pages: int
    raw_evidence_bytes: int
    database_writes: int


async def persist_http_traces(
    session: AsyncSession,
    traces: list[LogicalRequestTrace],
    *,
    execution_no: int,
    sync_run_id: UUID | None = None,
    scrape_target_id: UUID | None = None,
) -> TracePersistenceStats:
    """Persist completed requests, attempts, and content-addressed evidence."""

    if (sync_run_id is None) == (scrape_target_id is None):
        raise ValueError("exactly one HTTP trace owner is required")
    logical_requests = 0
    physical_attempts = 0
    catalog_pages = 0
    raw_evidence_bytes = 0
    writes = 0
    for trace in traces:
        if trace.finished_at is None or trace.outcome == "running":
            raise ValueError("only completed logical request traces can be persisted")
        evidence_blob: ScrapeEvidenceBlob | None = None
        if trace.raw_body is not None and trace.content_sha256 is not None:
            actual_hash = hashlib.sha256(trace.raw_body).hexdigest()
            if actual_hash != trace.content_sha256:
                raise EvidenceIntegrityError(
                    "HTTP trace SHA-256 does not match the retained response body"
                )
            compressed = zlib.compress(trace.raw_body, level=6)
            inserted_id = await session.scalar(
                insert(ScrapeEvidenceBlob)
                .values(
                    id=uuid4(),
                    content_sha256=trace.content_sha256,
                    content_zlib=compressed,
                    raw_size_bytes=len(trace.raw_body),
                    stored_size_bytes=len(compressed),
                    content_type=trace.response_content_type,
                    encoding=trace.response_encoding,
                )
                .on_conflict_do_nothing(
                    index_elements=[ScrapeEvidenceBlob.content_sha256],
                )
                .returning(ScrapeEvidenceBlob.id)
            )
            if inserted_id is not None:
                raw_evidence_bytes += len(trace.raw_body)
                writes += 1
            evidence_blob = await session.scalar(
                select(ScrapeEvidenceBlob)
                .where(ScrapeEvidenceBlob.content_sha256 == trace.content_sha256)
                .with_for_update(read=True, key_share=True)
            )
            if evidence_blob is None:
                raise EvidenceIntegrityError(
                    "Content-addressed evidence insert did not produce a blob"
                )

        request = ScrapeHttpRequest(
            sync_run_id=sync_run_id,
            scrape_target_id=scrape_target_id,
            evidence_blob_id=evidence_blob.id if evidence_blob else None,
            execution_no=execution_no,
            sequence_no=trace.sequence_no,
            request_kind=trace.request_kind,
            request_key=trace.request_key,
            prepared_url=trace.prepared_url,
            outcome=trace.outcome,
            replayed=trace.replayed,
            attempt_count=len(trace.attempts),
            response_status_code=trace.response_status_code,
            latency_ms=trace.latency_ms,
            rate_wait_ms=trace.total_rate_wait_ms,
            backoff_ms=trace.total_backoff_ms,
            error_category=trace.error_category,
            error_detail=(trace.error_detail or "")[:4000] or None,
            started_at=trace.started_at,
            finished_at=trace.finished_at,
        )
        session.add(request)
        await session.flush()
        writes += 1
        logical_requests += 1
        if trace.request_kind == "catalog_page":
            catalog_pages += 1
        for attempt in trace.attempts:
            session.add(
                ScrapeHttpAttempt(
                    logical_request_id=request.id,
                    attempt_no=attempt.attempt_no,
                    outcome=attempt.outcome,
                    status_code=attempt.status_code,
                    status_class=attempt.status_class,
                    latency_ms=attempt.latency_ms,
                    local_rate_wait_ms=attempt.local_rate_wait_ms,
                    global_rate_wait_ms=attempt.global_rate_wait_ms,
                    retry_backoff_ms=attempt.retry_backoff_ms,
                    error_category=attempt.error_category,
                    error_detail=(attempt.error_detail or "")[:4000] or None,
                    started_at=attempt.started_at,
                )
            )
            physical_attempts += 1
            writes += 1
    return TracePersistenceStats(
        logical_requests=logical_requests,
        physical_attempts=physical_attempts,
        catalog_pages=catalog_pages,
        raw_evidence_bytes=raw_evidence_bytes,
        database_writes=writes,
    )


async def load_replay_cache(
    session: AsyncSession,
    *,
    sync_run_id: UUID | None = None,
    scrape_target_id: UUID | None = None,
) -> dict[str, ReplayEvidence]:
    """Load the newest valid raw response for every request fingerprint."""

    if (sync_run_id is None) == (scrape_target_id is None):
        raise ValueError("exactly one replay owner is required")
    predicate = (
        ScrapeHttpRequest.sync_run_id == sync_run_id
        if sync_run_id is not None
        else ScrapeHttpRequest.scrape_target_id == scrape_target_id
    )
    rows = list(
        (
            await session.execute(
                select(ScrapeHttpRequest, ScrapeEvidenceBlob)
                .join(
                    ScrapeEvidenceBlob,
                    ScrapeEvidenceBlob.id == ScrapeHttpRequest.evidence_blob_id,
                )
                .where(
                    predicate,
                    ScrapeHttpRequest.outcome.in_(("success", "replayed")),
                )
                .order_by(
                    ScrapeHttpRequest.execution_no.desc(),
                    ScrapeHttpRequest.sequence_no.desc(),
                )
            )
        ).all()
    )
    replay: dict[str, ReplayEvidence] = {}
    for request, blob in rows:
        if request.request_key in replay:
            continue
        try:
            body = zlib.decompress(blob.content_zlib)
        except zlib.error as exc:
            raise EvidenceIntegrityError(
                f"Evidence blob {blob.id} cannot be decompressed"
            ) from exc
        actual_hash = hashlib.sha256(body).hexdigest()
        if actual_hash != blob.content_sha256:
            raise EvidenceIntegrityError(
                f"Evidence blob {blob.id} failed SHA-256 verification"
            )
        if len(body) != blob.raw_size_bytes:
            raise EvidenceIntegrityError(
                f"Evidence blob {blob.id} has an invalid raw size"
            )
        replay[request.request_key] = ReplayEvidence(
            request_key=request.request_key,
            body=body,
            status_code=request.response_status_code or 200,
            encoding=blob.encoding,
            content_type=blob.content_type,
            content_sha256=blob.content_sha256,
        )
    return replay


async def evidence_coverage_ratio(
    session: AsyncSession,
    *,
    sync_run_id: UUID | None = None,
    scrape_target_id: UUID | None = None,
    execution_no: int | None = None,
) -> Decimal:
    if (sync_run_id is None) == (scrape_target_id is None):
        raise ValueError("exactly one evidence owner is required")
    predicate = (
        ScrapeHttpRequest.sync_run_id == sync_run_id
        if sync_run_id is not None
        else ScrapeHttpRequest.scrape_target_id == scrape_target_id
    )
    conditions = [predicate]
    if execution_no is not None:
        conditions.append(ScrapeHttpRequest.execution_no == execution_no)
    rows = list(
        (
            await session.execute(
                select(
                    ScrapeHttpRequest.outcome,
                    ScrapeHttpRequest.evidence_blob_id,
                ).where(*conditions)
            )
        ).all()
    )
    if not rows:
        return Decimal("0")
    evidenced = sum(
        outcome in {"success", "replayed"} and blob_id is not None
        for outcome, blob_id in rows
    )
    return (Decimal(evidenced) / Decimal(len(rows))).quantize(Decimal("0.000001"))


async def delete_orphaned_evidence_blobs(
    session: AsyncSession,
    *,
    limit: int = 1000,
) -> int:
    """Delete unreferenced content blobs in bounded maintenance batches."""

    if limit < 1:
        raise ValueError("limit must be at least one")
    orphan_ids = (
        select(ScrapeEvidenceBlob.id)
        .where(
            ~exists(
                select(ScrapeHttpRequest.id).where(
                    ScrapeHttpRequest.evidence_blob_id == ScrapeEvidenceBlob.id
                )
            )
        )
        .order_by(ScrapeEvidenceBlob.created_at, ScrapeEvidenceBlob.id)
        .limit(limit)
    )
    result = await session.execute(
        delete(ScrapeEvidenceBlob).where(ScrapeEvidenceBlob.id.in_(orphan_ids))
    )
    await session.commit()
    return int(result.rowcount or 0)


async def retained_raw_evidence_bytes(
    session: AsyncSession,
    *,
    sync_run_id: UUID | None = None,
    scrape_target_id: UUID | None = None,
) -> int:
    if (sync_run_id is None) == (scrape_target_id is None):
        raise ValueError("exactly one evidence owner is required")
    predicate = (
        ScrapeHttpRequest.sync_run_id == sync_run_id
        if sync_run_id is not None
        else ScrapeHttpRequest.scrape_target_id == scrape_target_id
    )
    blob_ids = (
        select(ScrapeHttpRequest.evidence_blob_id)
        .where(predicate, ScrapeHttpRequest.evidence_blob_id.is_not(None))
        .distinct()
    )
    return int(
        await session.scalar(
            select(func.coalesce(func.sum(ScrapeEvidenceBlob.raw_size_bytes), 0)).where(
                ScrapeEvidenceBlob.id.in_(blob_ids)
            )
        )
        or 0
    )


__all__ = [
    "EvidenceIntegrityError",
    "TracePersistenceStats",
    "delete_orphaned_evidence_blobs",
    "evidence_coverage_ratio",
    "load_replay_cache",
    "persist_http_traces",
    "retained_raw_evidence_bytes",
]
