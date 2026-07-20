"""Relational persistence models for accounts, listings, prices, and matches."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class WorkspaceRole(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    member = "member"


class StoreKind(str, enum.Enum):
    owned = "owned"
    competitor = "competitor"


class MatchSource(str, enum.Enum):
    manual = "manual"
    automatic = "automatic"


class MatchStatus(str, enum.Enum):
    candidate = "candidate"
    approved = "approved"
    rejected = "rejected"


class SyncStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    firebase_uid: Mapped[str | None] = mapped_column(
        String(128), unique=True, index=True
    )
    email: Mapped[str] = mapped_column(String(320), index=True)
    display_name: Mapped[str | None] = mapped_column(String(160))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )


class Workspace(TimestampMixin, Base):
    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("slug"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160))
    slug: Mapped[str] = mapped_column(String(100), index=True)


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[WorkspaceRole] = mapped_column(
        Enum(WorkspaceRole, name="workspace_role"), default=WorkspaceRole.member
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MarketplaceStore(TimestampMixin, Base):
    __tablename__ = "marketplace_stores"
    __table_args__ = (
        UniqueConstraint(
            "marketplace", "external_id", name="uq_store_marketplace_external"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    marketplace: Mapped[str] = mapped_column(
        String(32), default="prom", server_default="prom"
    )
    external_id: Mapped[str] = mapped_column(String(100))
    name: Mapped[str | None] = mapped_column(String(255))
    canonical_url: Mapped[str] = mapped_column(Text)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkspaceStore(TimestampMixin, Base):
    __tablename__ = "workspace_stores"
    __table_args__ = (
        UniqueConstraint("workspace_id", "store_id", name="uq_workspace_store"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("marketplace_stores.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[StoreKind] = mapped_column(Enum(StoreKind, name="store_kind"))


class Listing(TimestampMixin, Base):
    __tablename__ = "listings"
    __table_args__ = (
        UniqueConstraint("store_id", "external_id", name="uq_listing_store_external"),
        Index("ix_listing_model_id", "model_id"),
        Index("ix_listing_sku", "sku"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    store_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("marketplace_stores.id", ondelete="CASCADE"), index=True
    )
    external_id: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    sku: Mapped[str | None] = mapped_column(String(255))
    model_id: Mapped[str | None] = mapped_column(String(255))
    brand: Mapped[str | None] = mapped_column(String(255))
    currency: Mapped[str] = mapped_column(
        String(3), default="UAH", server_default="UAH"
    )
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    is_available: Mapped[bool | None] = mapped_column(Boolean)
    raw_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    @property
    def image_url(self) -> str | None:
        raw_data = self.raw_data
        if not isinstance(raw_data, dict):
            return None
        value = raw_data.get("image")
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        if not normalized.startswith(("https://", "http://")):
            return None
        return normalized


class PriceObservation(Base):
    __tablename__ = "price_observations"
    __table_args__ = (
        UniqueConstraint(
            "sync_run_id",
            "listing_id",
            name="uq_price_observation_sync_listing",
        ),
        Index("ix_price_observation_listing_time", "listing_id", "observed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    listing_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), index=True
    )
    sync_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sync_runs.id", ondelete="SET NULL"), index=True
    )
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3))
    currency_raw: Mapped[str | None] = mapped_column(String(32))
    currency_inferred: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    is_available: Mapped[bool | None] = mapped_column(Boolean)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ProductMatch(TimestampMixin, Base):
    __tablename__ = "product_matches"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "source_listing_id",
            "candidate_listing_id",
            name="uq_product_match",
        ),
        CheckConstraint(
            "source_listing_id <> candidate_listing_id",
            name="ck_product_match_distinct",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    source_listing_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), index=True
    )
    candidate_listing_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[MatchSource] = mapped_column(Enum(MatchSource, name="match_source"))
    status: Mapped[MatchStatus] = mapped_column(
        Enum(MatchStatus, name="match_status"), default=MatchStatus.candidate
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    matcher_version: Mapped[str | None] = mapped_column(String(50))


class SyncRun(TimestampMixin, Base):
    __tablename__ = "sync_runs"
    __table_args__ = (
        CheckConstraint(
            "scrape_state IN ('queued', 'running', 'retry_wait', "
            "'succeeded', 'failed', 'cancelled')",
            name="ck_sync_run_scrape_state",
        ),
        CheckConstraint(
            "scrape_task_executions >= 0 AND scrape_task_redeliveries >= 0 "
            "AND scrape_deduplicated_submissions >= 0",
            name="ck_sync_run_scrape_task_counts",
        ),
        CheckConstraint(
            "scrape_catalog_pages >= 0 AND scrape_products_extracted >= 0 "
            "AND scrape_products_persisted >= 0 "
            "AND scrape_duplicate_products >= 0 AND scrape_database_writes >= 0 "
            "AND scrape_raw_evidence_bytes >= 0",
            name="ck_sync_run_scrape_output_counts",
        ),
        CheckConstraint(
            "scrape_structured_completeness IS NULL OR "
            "(scrape_structured_completeness >= 0 "
            "AND scrape_structured_completeness <= 1)",
            name="ck_sync_run_scrape_completeness",
        ),
        CheckConstraint(
            "scrape_evidence_coverage IS NULL OR "
            "(scrape_evidence_coverage >= 0 AND scrape_evidence_coverage <= 1)",
            name="ck_sync_run_scrape_evidence_coverage",
        ),
        Index("ix_sync_run_workspace_status", "workspace_id", "status"),
        Index("ix_sync_run_scrape_state", "scrape_state"),
        Index(
            "uq_sync_run_active_store_sync",
            "workspace_id",
            "store_id",
            unique=True,
            postgresql_where=text(
                "kind = 'catalog_import' "
                "AND store_id IS NOT NULL "
                "AND scrape_state IN ('queued', 'running', 'retry_wait')"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    store_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("marketplace_stores.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str] = mapped_column(String(50))
    scrape_item_version: Mapped[str] = mapped_column(
        String(80),
        default="store-sync-v1",
        server_default="store-sync-v1",
    )
    scrape_input_fingerprint: Mapped[str | None] = mapped_column(
        String(64),
        index=True,
    )
    scrape_state: Mapped[str] = mapped_column(
        String(20),
        default="queued",
        server_default="queued",
    )
    scrape_deduplicated_submissions: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
    )
    scrape_task_executions: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
    )
    scrape_task_redeliveries: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
    )
    scrape_max_task_executions: Mapped[int] = mapped_column(
        Integer,
        default=3,
        server_default="3",
    )
    scrape_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scrape_owner_task_id: Mapped[str | None] = mapped_column(
        String(255),
        index=True,
    )
    scrape_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    scrape_fencing_token: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
        server_default="0",
    )
    scrape_checkpoint: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    scrape_catalog_pages: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
    )
    scrape_products_extracted: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
    )
    scrape_products_persisted: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
    )
    scrape_duplicate_products: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
    )
    scrape_database_writes: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
        server_default="0",
    )
    scrape_raw_evidence_bytes: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
        server_default="0",
    )
    scrape_structured_completeness: Mapped[Decimal | None] = mapped_column(
        Numeric(7, 6)
    )
    scrape_evidence_coverage: Mapped[Decimal | None] = mapped_column(Numeric(7, 6))
    status: Mapped[SyncStatus] = mapped_column(
        Enum(SyncStatus, name="sync_status"), default=SyncStatus.queued
    )
    task_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    progress_current: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    progress_total: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StoreSyncTaskExecution(Base):
    """One task execution/redelivery for a store-sync logical item."""

    __tablename__ = "store_sync_task_executions"
    __table_args__ = (
        UniqueConstraint(
            "sync_run_id",
            "execution_no",
            name="uq_store_sync_task_execution_no",
        ),
        CheckConstraint(
            "execution_no > 0 AND wall_time_ms >= 0 AND cpu_time_ms >= 0 "
            "AND memory_peak_bytes >= 0 AND fencing_token > 0",
            name="ck_store_sync_task_execution_measurements",
        ),
        CheckConstraint(
            "outcome IN ('running', 'succeeded', 'retryable_failure', "
            "'terminal_failure', 'worker_lost')",
            name="ck_store_sync_task_execution_outcome",
        ),
        Index(
            "ix_store_sync_task_execution_run_outcome",
            "sync_run_id",
            "outcome",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    sync_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sync_runs.id", ondelete="CASCADE"),
        index=True,
    )
    task_id: Mapped[str | None] = mapped_column(String(255), index=True)
    execution_no: Mapped[int] = mapped_column(Integer)
    fencing_token: Mapped[int] = mapped_column(BigInteger)
    is_redelivery: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
    )
    redelivery_reason: Mapped[str | None] = mapped_column(String(100))
    outcome: Mapped[str] = mapped_column(
        String(24),
        default="running",
        server_default="running",
    )
    error_category: Mapped[str | None] = mapped_column(String(50))
    error_detail: Mapped[str | None] = mapped_column(Text)
    wall_time_ms: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
        server_default="0",
    )
    cpu_time_ms: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
        server_default="0",
    )
    memory_peak_bytes: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
        server_default="0",
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ScrapeDispatchOutbox(TimestampMixin, Base):
    """Durable DB-to-broker handoff for scraper and pricing workflow tasks."""

    __tablename__ = "scrape_dispatch_outbox"
    __table_args__ = (
        UniqueConstraint("event_key", name="uq_scrape_dispatch_outbox_event_key"),
        UniqueConstraint("task_id", name="uq_scrape_dispatch_outbox_task_id"),
        CheckConstraint(
            "status IN ('pending', 'dispatching', 'published', 'terminal_failed')",
            name="ck_scrape_dispatch_outbox_status",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND max_attempts > 0",
            name="ck_scrape_dispatch_outbox_attempts",
        ),
        Index(
            "ix_scrape_dispatch_outbox_ready",
            "status",
            "available_at",
            "created_at",
        ),
        Index(
            "ix_scrape_dispatch_outbox_aggregate",
            "aggregate_type",
            "aggregate_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_key: Mapped[str] = mapped_column(String(255))
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    aggregate_type: Mapped[str] = mapped_column(String(80))
    aggregate_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    task_name: Mapped[str] = mapped_column(String(255))
    task_id: Mapped[str] = mapped_column(String(255))
    queue: Mapped[str | None] = mapped_column(String(100))
    task_args: Mapped[list[Any]] = mapped_column(JSON, default=list)
    task_kwargs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(
        String(24), default="pending", server_default="pending"
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, default=20, server_default="20")
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class StoreSyncProductSnapshot(Base):
    """Immutable structured product output emitted by one store-sync run."""

    __tablename__ = "store_sync_product_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "sync_run_id",
            "external_id",
            name="uq_store_sync_product_snapshot_external",
        ),
        CheckConstraint(
            "structured_size_bytes >= 0",
            name="ck_store_sync_product_snapshot_size",
        ),
        CheckConstraint(
            "structured_completeness >= 0 AND structured_completeness <= 1",
            name="ck_store_sync_product_snapshot_completeness",
        ),
        Index(
            "ix_store_sync_product_snapshot_run",
            "sync_run_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    sync_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sync_runs.id", ondelete="CASCADE"),
    )
    listing_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("listings.id", ondelete="SET NULL"),
        index=True,
    )
    external_id: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    structured_size_bytes: Mapped[int] = mapped_column(BigInteger)
    structured_completeness: Mapped[Decimal] = mapped_column(Numeric(7, 6))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class ScrapeEvidenceBlob(Base):
    """Content-addressed compressed immutable raw HTTP evidence."""

    __tablename__ = "scrape_evidence_blobs"
    __table_args__ = (
        UniqueConstraint(
            "content_sha256",
            name="uq_scrape_evidence_blobs_content_sha256",
        ),
        CheckConstraint(
            "raw_size_bytes >= 0 AND stored_size_bytes >= 0",
            name="ck_scrape_evidence_blob_sizes",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    content_sha256: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
    )
    content_zlib: Mapped[bytes] = mapped_column(LargeBinary)
    raw_size_bytes: Mapped[int] = mapped_column(BigInteger)
    stored_size_bytes: Mapped[int] = mapped_column(BigInteger)
    content_type: Mapped[str | None] = mapped_column(String(255))
    encoding: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class ScrapeHttpRequest(Base):
    """One logical HTTP request within one task execution."""

    __tablename__ = "scrape_http_requests"
    __table_args__ = (
        UniqueConstraint(
            "sync_run_id",
            "execution_no",
            "sequence_no",
            name="uq_scrape_http_request_sync_execution_sequence",
        ),
        UniqueConstraint(
            "scrape_target_id",
            "execution_no",
            "sequence_no",
            name="uq_scrape_http_request_target_execution_sequence",
        ),
        CheckConstraint(
            "(sync_run_id IS NOT NULL AND scrape_target_id IS NULL) OR "
            "(sync_run_id IS NULL AND scrape_target_id IS NOT NULL)",
            name="ck_scrape_http_request_one_owner",
        ),
        CheckConstraint(
            "outcome IN ('success', 'replayed', 'retryable_failure', "
            "'terminal_failure')",
            name="ck_scrape_http_request_outcome",
        ),
        CheckConstraint(
            "execution_no > 0 AND sequence_no > 0 AND attempt_count >= 0 "
            "AND latency_ms >= 0 AND rate_wait_ms >= 0 AND backoff_ms >= 0",
            name="ck_scrape_http_request_measurements",
        ),
        Index(
            "ix_scrape_http_request_sync_kind",
            "sync_run_id",
            "request_kind",
        ),
        Index(
            "ix_scrape_http_request_target_kind",
            "scrape_target_id",
            "request_kind",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    sync_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sync_runs.id", ondelete="CASCADE"),
        index=True,
    )
    scrape_target_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("scrape_targets.id", ondelete="CASCADE"),
        index=True,
    )
    evidence_blob_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("scrape_evidence_blobs.id", ondelete="RESTRICT"),
        index=True,
    )
    execution_no: Mapped[int] = mapped_column(Integer)
    sequence_no: Mapped[int] = mapped_column(Integer)
    request_kind: Mapped[str] = mapped_column(String(50), index=True)
    request_key: Mapped[str] = mapped_column(String(64), index=True)
    prepared_url: Mapped[str] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(String(24))
    replayed: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
    )
    response_status_code: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
        server_default="0",
    )
    rate_wait_ms: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
        server_default="0",
    )
    backoff_ms: Mapped[int] = mapped_column(
        BigInteger,
        default=0,
        server_default="0",
    )
    error_category: Mapped[str | None] = mapped_column(String(50))
    error_detail: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ScrapeHttpAttempt(Base):
    """One physical network attempt for a logical HTTP request."""

    __tablename__ = "scrape_http_attempts"
    __table_args__ = (
        UniqueConstraint(
            "logical_request_id",
            "attempt_no",
            name="uq_scrape_http_attempt_request_no",
        ),
        CheckConstraint(
            "outcome IN ('success', 'retryable_failure', 'terminal_failure')",
            name="ck_scrape_http_attempt_outcome",
        ),
        CheckConstraint(
            "attempt_no > 0 AND latency_ms >= 0 AND local_rate_wait_ms >= 0 "
            "AND global_rate_wait_ms >= 0 AND retry_backoff_ms >= 0",
            name="ck_scrape_http_attempt_measurements",
        ),
        Index(
            "ix_scrape_http_attempt_outcome_status",
            "outcome",
            "status_class",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    logical_request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scrape_http_requests.id", ondelete="CASCADE"),
        index=True,
    )
    attempt_no: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(24))
    status_code: Mapped[int | None] = mapped_column(Integer)
    status_class: Mapped[str] = mapped_column(String(20))
    latency_ms: Mapped[int] = mapped_column(BigInteger)
    local_rate_wait_ms: Mapped[int] = mapped_column(BigInteger)
    global_rate_wait_ms: Mapped[int] = mapped_column(BigInteger)
    retry_backoff_ms: Mapped[int] = mapped_column(BigInteger)
    error_category: Mapped[str | None] = mapped_column(String(50))
    error_detail: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CatalogImportBatch(TimestampMixin, Base):
    __tablename__ = "catalog_import_batches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'partial', 'failed')",
            name="ck_catalog_import_batch_status",
        ),
        Index(
            "ix_catalog_import_batch_workspace_created", "workspace_id", "created_at"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    content_size: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(16), default="queued", server_default="queued"
    )
    column_mapping: Mapped[dict[str, Any]] = mapped_column(JSON)
    total_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    imported_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    rejected_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_log: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CatalogItem(TimestampMixin, Base):
    __tablename__ = "catalog_items"
    __table_args__ = (
        UniqueConstraint("import_batch_id", "sku", name="uq_catalog_item_batch_sku"),
        CheckConstraint("current_price > 0", name="ck_catalog_item_price_positive"),
        CheckConstraint(
            "stock_status IN ('fresh', 'stale', 'dead_stock', 'unknown')",
            name="ck_catalog_item_stock_status",
        ),
        CheckConstraint(
            "cost IS NULL OR cost > 0", name="ck_catalog_item_cost_positive"
        ),
        CheckConstraint(
            "stock_qty IS NULL OR stock_qty >= 0",
            name="ck_catalog_item_stock_qty_nonnegative",
        ),
        CheckConstraint(
            "(units_sold_30d IS NULL OR units_sold_30d >= 0) AND "
            "(units_sold_60d IS NULL OR units_sold_60d >= 0) AND "
            "(units_sold_90d IS NULL OR units_sold_90d >= 0) AND "
            "(days_since_last_sale IS NULL OR days_since_last_sale >= 0) AND "
            "(historical_monthly_units IS NULL OR historical_monthly_units >= 0) AND "
            "(views_30d IS NULL OR views_30d >= 0) AND "
            "(conversion_rate_proxy IS NULL OR "
            "(conversion_rate_proxy >= 0 AND conversion_rate_proxy <= 1))",
            name="ck_catalog_items_sales_nonnegative",
        ),
        Index("ix_catalog_item_workspace_oe", "workspace_id", "oe_norm"),
        Index("ix_catalog_item_workspace_category", "workspace_id", "category"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    import_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_import_batches.id", ondelete="CASCADE"), index=True
    )
    store_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("marketplace_stores.id", ondelete="SET NULL"), index=True
    )
    source_row: Mapped[int] = mapped_column(Integer)
    sku: Mapped[str] = mapped_column(String(255))
    oe_raw: Mapped[str] = mapped_column(Text)
    oe_norm: Mapped[str] = mapped_column(String(255), index=True)
    mpn_raw: Mapped[str] = mapped_column(Text, default="", server_default="")
    mpn_norm: Mapped[str] = mapped_column(String(255), default="", server_default="")
    name: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(255), index=True)
    brand: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    product_url: Mapped[str | None] = mapped_column(Text)
    current_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(
        String(3), default="UAH", server_default="UAH"
    )
    is_available: Mapped[bool | None] = mapped_column(Boolean)
    stock_status: Mapped[str] = mapped_column(
        String(16), default="unknown", server_default="unknown"
    )
    stock_qty: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    stock_age_days: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    expected_units_sold: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    units_sold_30d: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    units_sold_60d: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    units_sold_90d: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    days_since_last_sale: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    historical_monthly_units: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    views_30d: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    conversion_rate_proxy: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    manual_priority: Mapped[Decimal] = mapped_column(
        Numeric(8, 4), default=Decimal("1"), server_default="1"
    )
    raw_row: Mapped[dict[str, Any]] = mapped_column(JSON)


class CatalogItemOverride(Base):
    """Append-only operator context layered over an imported catalog row."""

    __tablename__ = "catalog_item_overrides"
    __table_args__ = (
        CheckConstraint(
            "stock_status IS NULL OR stock_status IN ('fresh', 'stale', 'dead_stock', 'unknown')",
            name="ck_catalog_item_override_stock_status",
        ),
        CheckConstraint(
            "cost IS NULL OR cost > 0", name="ck_catalog_item_override_cost"
        ),
        CheckConstraint(
            "stock_qty IS NULL OR stock_qty >= 0",
            name="ck_catalog_item_override_stock_qty",
        ),
        CheckConstraint(
            "below_cost_floor IS NULL OR below_cost_floor >= 0",
            name="ck_catalog_item_override_below_cost_floor",
        ),
        CheckConstraint(
            "(units_sold_30d IS NULL OR units_sold_30d >= 0) AND "
            "(units_sold_60d IS NULL OR units_sold_60d >= 0) AND "
            "(units_sold_90d IS NULL OR units_sold_90d >= 0) AND "
            "(days_since_last_sale IS NULL OR days_since_last_sale >= 0) AND "
            "(historical_monthly_units IS NULL OR historical_monthly_units >= 0) AND "
            "(views_30d IS NULL OR views_30d >= 0) AND "
            "(conversion_rate_proxy IS NULL OR "
            "(conversion_rate_proxy >= 0 AND conversion_rate_proxy <= 1))",
            name="ck_catalog_item_overrides_sales_nonnegative",
        ),
        CheckConstraint(
            "NOT allow_below_cost OR below_cost_warning_confirmed",
            name="ck_catalog_item_override_below_cost_authorization",
        ),
        Index(
            "ix_catalog_item_override_current", "catalog_item_id", "created_at", "id"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    catalog_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_items.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    stock_status: Mapped[str | None] = mapped_column(String(16))
    cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    stock_qty: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    stock_age_days: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    expected_units_sold: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    units_sold_30d: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    units_sold_60d: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    units_sold_90d: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    days_since_last_sale: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    historical_monthly_units: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    views_30d: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    conversion_rate_proxy: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    manual_priority: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    liquidity_target: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    urgency: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    allow_below_cost: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    below_cost_floor: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    below_cost_warning_confirmed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CatalogItemCostRecord(Base):
    """Append-only encrypted unit-cost value or explicit clear tombstone."""

    __tablename__ = "catalog_item_cost_records"
    __table_args__ = (
        CheckConstraint(
            "action IN ('SET', 'CLEAR')",
            name="ck_catalog_item_cost_record_action",
        ),
        CheckConstraint(
            "(action = 'SET' AND ciphertext IS NOT NULL AND nonce IS NOT NULL "
            "AND octet_length(nonce) = 12 "
            "AND octet_length(ciphertext) BETWEEN 20 AND 31 "
            "AND key_id IS NOT NULL AND algorithm = 'AES-256-GCM' "
            "AND format_version = 1) OR "
            "(action = 'CLEAR' AND ciphertext IS NULL AND nonce IS NULL "
            "AND key_id IS NULL AND algorithm IS NULL AND format_version IS NULL)",
            name="ck_catalog_item_cost_record_payload",
        ),
        UniqueConstraint("sequence_no", name="uq_catalog_item_cost_record_sequence"),
        UniqueConstraint(
            "key_id", "nonce", name="uq_catalog_item_cost_record_key_nonce"
        ),
        Index(
            "ix_catalog_item_cost_record_current",
            "workspace_id",
            "catalog_item_id",
            "sequence_no",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    sequence_no: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    catalog_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_items.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(8))
    ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    nonce: Mapped[bytes | None] = mapped_column(LargeBinary)
    key_id: Mapped[str | None] = mapped_column(String(64))
    algorithm: Mapped[str | None] = mapped_column(String(32))
    format_version: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PricingPolicyRecord(TimestampMixin, Base):
    __tablename__ = "pricing_policies"
    __table_args__ = (
        UniqueConstraint("workspace_id", "version", name="uq_pricing_policy_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[str] = mapped_column(String(80))
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )


class PricingRun(TimestampMixin, Base):
    __tablename__ = "pricing_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'collecting', 'classifying', 'calibrating', "
            "'calculating', 'completed', 'partial', 'failed', 'cancelled')",
            name="ck_pricing_run_status",
        ),
        Index("ix_pricing_run_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    import_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_import_batches.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default="queued", server_default="queued"
    )
    policy_version: Mapped[str] = mapped_column(String(80))
    policy_config: Mapped[dict[str, Any]] = mapped_column(JSON)
    parser_version: Mapped[str] = mapped_column(String(80))
    classifier_version: Mapped[str] = mapped_column(
        String(80), default="brand-tier-v1", server_default="brand-tier-v1"
    )
    coefficient_model: Mapped[str] = mapped_column(
        String(32), default="shrinkage", server_default="shrinkage"
    )
    coefficient_version: Mapped[str | None] = mapped_column(String(160))
    calibration_dataset_hash: Mapped[str | None] = mapped_column(String(64))
    calibration_accounting: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
    calibration_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    calibration_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    total_items: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    completed_items: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    failed_items: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    manual_review_items: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    finalizer_task_id: Mapped[str | None] = mapped_column(String(255))
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ScrapeTarget(TimestampMixin, Base):
    """One deduplicated black-box extraction input inside a pricing run."""

    __tablename__ = "scrape_targets"
    __table_args__ = (
        UniqueConstraint(
            "pricing_run_id",
            "input_hash",
            name="uq_scrape_target_run_input_hash",
        ),
        CheckConstraint(
            "status IN ('queued', 'collecting', 'retryable_failure', "
            "'succeeded', 'terminal_failure', 'cancelled')",
            name="ck_scrape_target_status",
        ),
        CheckConstraint(
            "delivery_count >= 0 AND network_attempts >= 0 "
            "AND max_task_executions > 0 AND freshness_generation >= 0 "
            "AND fencing_token >= 0",
            name="ck_scrape_target_attempt_counts",
        ),
        CheckConstraint(
            "raw_size_bytes >= 0 AND structured_size_bytes >= 0 "
            "AND metadata_size_bytes >= 0",
            name="ck_scrape_target_storage_sizes",
        ),
        CheckConstraint(
            "structured_completeness IS NULL OR "
            "(structured_completeness >= 0 AND structured_completeness <= 1)",
            name="ck_scrape_target_completeness",
        ),
        CheckConstraint(
            "source_policy_state IN "
            "('PERMITTED', 'OWNER_RISK_ACCEPTED', 'NOT_PERMITTED', 'UNKNOWN')",
            name="ck_scrape_target_source_policy_state",
        ),
        CheckConstraint(
            "source_lane IN "
            "('OWNED_STOREFRONT', 'PUBLIC_COMPETITOR', 'REPLAY', 'CLIENT_EXPORT')",
            name="ck_scrape_target_source_lane",
        ),
        CheckConstraint(
            "execution_status IN ('QUEUED', 'RUNNING', 'RETRY_WAIT', "
            "'SUCCEEDED', 'TERMINAL_FAILED', 'CANCELLED', 'DEAD_LETTERED')",
            name="ck_scrape_target_execution_status",
        ),
        CheckConstraint(
            "acquisition_status IN ('NOT_STARTED', 'SUCCEEDED', 'FAILED', 'BLOCKED')",
            name="ck_scrape_target_acquisition_status",
        ),
        CheckConstraint(
            "parse_status IN "
            "('NOT_STARTED', 'SUCCEEDED', 'PARTIAL', 'FAILED', 'NOT_APPLICABLE')",
            name="ck_scrape_target_parse_status",
        ),
        CheckConstraint(
            "evidence_status IN "
            "('NONE', 'RAW_AVAILABLE', 'STRUCTURED_AVAILABLE', 'INGESTED', "
            "'INTEGRITY_FAILED')",
            name="ck_scrape_target_evidence_status",
        ),
        CheckConstraint(
            "downstream_eligibility IN ('ELIGIBLE', 'INELIGIBLE', 'UNKNOWN')",
            name="ck_scrape_target_downstream_eligibility",
        ),
        CheckConstraint(
            "operator_action IN ('NONE', 'MANUAL_REVIEW_REQUIRED', "
            "'REPLAY_REQUIRED', 'NO_RECOMMENDATION')",
            name="ck_scrape_target_operator_action",
        ),
        CheckConstraint(
            "input_kind IN ('product_seed', 'query')",
            name="ck_scrape_target_input_kind",
        ),
        Index("ix_scrape_target_run_status", "pricing_run_id", "status"),
        Index("ix_scrape_target_acquisition_key", "acquisition_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    pricing_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pricing_runs.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(
        String(50), default="prom", server_default="prom"
    )
    source_type: Mapped[str] = mapped_column(
        String(50), default="prom_public", server_default="prom_public"
    )
    source_lane: Mapped[str] = mapped_column(
        String(32), default="PUBLIC_COMPETITOR", server_default="PUBLIC_COMPETITOR"
    )
    source_policy_decision_id: Mapped[str] = mapped_column(String(160), index=True)
    source_policy_version: Mapped[str] = mapped_column(String(160))
    source_policy_state: Mapped[str] = mapped_column(String(24))
    submission_key: Mapped[str] = mapped_column(String(64), index=True)
    acquisition_key: Mapped[str] = mapped_column(String(64))
    parse_key: Mapped[str | None] = mapped_column(String(64), index=True)
    freshness_generation: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    original_url: Mapped[str | None] = mapped_column(Text)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    product_key: Mapped[str | None] = mapped_column(String(100))
    input_kind: Mapped[str] = mapped_column(
        String(24), default="product_seed", server_default="product_seed"
    )
    query: Mapped[str] = mapped_column(String(255))
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    adapter_version: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(
        String(24), default="queued", server_default="queued"
    )
    owner_task_id: Mapped[str | None] = mapped_column(String(255), index=True)
    attempt_group_id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4)
    winning_attempt_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    fencing_token: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0"
    )
    delivery_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    network_attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    max_task_executions: Mapped[int] = mapped_column(
        Integer,
        default=4,
        server_default="4",
    )
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    parser_name: Mapped[str] = mapped_column(String(160))
    parser_config_hash: Mapped[str] = mapped_column(String(64))
    output_schema_version: Mapped[str] = mapped_column(String(160))
    execution_status: Mapped[str] = mapped_column(
        String(24), default="QUEUED", server_default="QUEUED"
    )
    acquisition_status: Mapped[str] = mapped_column(
        String(24), default="NOT_STARTED", server_default="NOT_STARTED"
    )
    parse_status: Mapped[str] = mapped_column(
        String(24), default="NOT_STARTED", server_default="NOT_STARTED"
    )
    evidence_status: Mapped[str] = mapped_column(
        String(32), default="NONE", server_default="NONE"
    )
    downstream_eligibility: Mapped[str] = mapped_column(
        String(24), default="UNKNOWN", server_default="UNKNOWN"
    )
    operator_action: Mapped[str] = mapped_column(
        String(32), default="NO_RECOMMENDATION", server_default="NO_RECOMMENDATION"
    )
    reason_codes: Mapped[list[str]] = mapped_column(JSON, default=list)
    content_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    raw_size_bytes: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0"
    )
    structured_size_bytes: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0"
    )
    metadata_size_bytes: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0"
    )
    structured_completeness: Mapped[Decimal | None] = mapped_column(Numeric(7, 6))
    error_category: Mapped[str | None] = mapped_column(String(50))
    error_detail: Mapped[str | None] = mapped_column(Text)
    first_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PricingRunItem(TimestampMixin, Base):
    __tablename__ = "pricing_run_items"
    __table_args__ = (
        UniqueConstraint(
            "pricing_run_id", "catalog_item_id", name="uq_pricing_run_item"
        ),
        UniqueConstraint("idempotency_key", name="uq_pricing_run_item_idempotency"),
        CheckConstraint(
            "status IN ('queued', 'collecting', 'collected', 'classified', "
            "'calculating', 'calculated', 'manual_review', 'failed', 'cancelled')",
            name="ck_pricing_run_item_status",
        ),
        Index("ix_pricing_run_item_run_status", "pricing_run_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    pricing_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pricing_runs.id", ondelete="CASCADE"), index=True
    )
    catalog_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_items.id", ondelete="CASCADE"), index=True
    )
    scrape_target_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("scrape_targets.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), default="queued", server_default="queued"
    )
    idempotency_key: Mapped[str] = mapped_column(String(160))
    task_id: Mapped[str | None] = mapped_column(String(255), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    checkpoint: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ScrapeAttempt(Base):
    """One worker delivery, including retries and idempotent duplicate skips."""

    __tablename__ = "scrape_attempts"
    __table_args__ = (
        UniqueConstraint(
            "scrape_target_id",
            "delivery_no",
            name="uq_scrape_attempt_target_delivery",
        ),
        CheckConstraint(
            "status IN ('running', 'succeeded', 'retryable_failure', "
            "'terminal_failure', 'duplicate', 'worker_lost')",
            name="ck_scrape_attempt_status",
        ),
        CheckConstraint(
            "delivery_no > 0 AND wall_time_ms >= 0 AND cpu_time_ms >= 0 "
            "AND memory_peak_bytes >= 0 AND fencing_token > 0",
            name="ck_scrape_attempt_measurements",
        ),
        CheckConstraint(
            "raw_size_bytes >= 0 AND structured_size_bytes >= 0 "
            "AND metadata_size_bytes >= 0",
            name="ck_scrape_attempt_storage_sizes",
        ),
        CheckConstraint(
            "structured_completeness IS NULL OR "
            "(structured_completeness >= 0 AND structured_completeness <= 1)",
            name="ck_scrape_attempt_completeness",
        ),
        Index("ix_scrape_attempt_target_status", "scrape_target_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    scrape_target_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scrape_targets.id", ondelete="CASCADE"), index=True
    )
    pricing_run_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pricing_run_items.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[str | None] = mapped_column(String(255), index=True)
    delivery_no: Mapped[int] = mapped_column(Integer)
    fencing_token: Mapped[int] = mapped_column(BigInteger)
    network_attempted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    status: Mapped[str] = mapped_column(
        String(24), default="running", server_default="running"
    )
    error_category: Mapped[str | None] = mapped_column(String(50))
    error_detail: Mapped[str | None] = mapped_column(Text)
    wall_time_ms: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    cpu_time_ms: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    memory_peak_bytes: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0"
    )
    raw_size_bytes: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0"
    )
    structured_size_bytes: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0"
    )
    metadata_size_bytes: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0"
    )
    structured_completeness: Mapped[Decimal | None] = mapped_column(Numeric(7, 6))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RawMarketCapture(Base):
    __tablename__ = "raw_market_captures"
    __table_args__ = (
        UniqueConstraint(
            "pricing_run_item_id",
            "content_sha256",
            name="uq_raw_market_capture_item_sha256",
        ),
        Index(
            "ix_raw_market_capture_run_item_time", "pricing_run_item_id", "captured_at"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    pricing_run_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pricing_run_items.id", ondelete="CASCADE"), index=True
    )
    scrape_target_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("scrape_targets.id", ondelete="SET NULL"), index=True
    )
    source: Mapped[str] = mapped_column(String(50))
    capture_kind: Mapped[str] = mapped_column(String(50), default="parser_output")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    parser_version: Mapped[str] = mapped_column(String(80))
    raw_size_bytes: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0"
    )
    structured_size_bytes: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0"
    )
    metadata_size_bytes: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0"
    )
    structured_completeness: Mapped[Decimal | None] = mapped_column(Numeric(7, 6))
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MarketObservation(Base):
    __tablename__ = "market_observations"
    __table_args__ = (
        UniqueConstraint(
            "pricing_run_item_id",
            "source",
            "source_listing_id",
            name="uq_market_observation_run_listing",
        ),
        CheckConstraint("price > 0", name="ck_market_observation_price_positive"),
        CheckConstraint(
            "match_confidence >= 0 AND match_confidence <= 1",
            name="ck_market_observation_match_confidence",
        ),
        CheckConstraint(
            "source_confidence >= 0 AND source_confidence <= 1",
            name="ck_market_observation_source_confidence",
        ),
        CheckConstraint(
            "NOT automatic_eligible OR (currency_raw IS NOT NULL AND "
            "comparison_evidence IS NOT NULL AND comparability_policy_id IS NOT NULL "
            "AND comparability_policy_hash IS NOT NULL AND "
            "char_length(comparability_policy_hash) = 64 AND "
            "seller_identity_verified AND source_provenance_verified AND "
            "oe_verification_status IN ('VERIFIED_EXACT', 'VERIFIED_CROSS') AND "
            "verified_matched_oe_norm IS NOT NULL AND "
            "comparison_identity_key IS NOT NULL AND "
            "comparability_hard_gate_result = 'PASS')",
            name="ck_market_observation_auto_evidence",
        ),
        CheckConstraint(
            "oe_verification_status IN ('VERIFIED_EXACT', 'VERIFIED_CROSS', "
            "'UNKNOWN', 'CONFLICT', 'AMBIGUOUS', 'LEGACY_UNVERIFIED')",
            name="ck_market_observation_oe_verification_status",
        ),
        CheckConstraint(
            "comparability_hard_gate_result IN ('PASS', 'MANUAL_REVIEW', 'REJECT')",
            name="ck_market_observation_comparability_result",
        ),
        CheckConstraint(
            "((oe_verification_status IN ('VERIFIED_EXACT', 'VERIFIED_CROSS') AND "
            "verified_matched_oe_norm IS NOT NULL AND comparison_identity_key IS NOT NULL) "
            "OR (oe_verification_status NOT IN ('VERIFIED_EXACT', 'VERIFIED_CROSS') AND "
            "verified_matched_oe_norm IS NULL AND comparison_identity_key IS NULL))",
            name="ck_market_observation_verified_identity",
        ),
        CheckConstraint(
            "condition_state IN ('NEW', 'USED_OR_REFURBISHED', 'CONFLICT', 'UNKNOWN')",
            name="ck_market_observation_condition_state",
        ),
        CheckConstraint(
            "(description_available AND description IS NOT NULL) OR "
            "(NOT description_available AND description IS NULL)",
            name="ck_market_observation_description_availability",
        ),
        CheckConstraint(
            "(url <> '' AND url_absence_reason IS NULL) OR "
            "(url = '' AND url_absence_reason IS NOT NULL)",
            name="ck_market_observation_url_or_reason",
        ),
        CheckConstraint(
            "(via_cross AND cross_link_id IS NOT NULL) OR "
            "(NOT via_cross AND cross_link_id IS NULL)",
            name="ck_market_observation_cross_provenance",
        ),
        Index("ix_market_observation_catalog_time", "catalog_item_id", "observed_at"),
        Index(
            "ix_market_observation_comparability_policy",
            "comparability_policy_id",
            "comparability_policy_hash",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    pricing_run_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pricing_run_items.id", ondelete="CASCADE"), index=True
    )
    catalog_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_items.id", ondelete="CASCADE"), index=True
    )
    raw_capture_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("raw_market_captures.id", ondelete="RESTRICT"), index=True
    )
    source: Mapped[str] = mapped_column(String(50))
    source_listing_id: Mapped[str] = mapped_column(String(255))
    seller_id: Mapped[str] = mapped_column(String(255))
    seller_name: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(Text)
    url_absence_reason: Mapped[str | None] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    description_available: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    condition_raw: Mapped[str | None] = mapped_column(Text)
    condition_state: Mapped[str] = mapped_column(
        String(32), default="UNKNOWN", server_default="UNKNOWN"
    )
    condition_reason_codes: Mapped[list[str]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    cross_candidates: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    brand_raw: Mapped[str | None] = mapped_column(String(255))
    # Deprecated compatibility field. New eligibility/calibration code must not read it.
    matched_oe_norm: Mapped[str | None] = mapped_column(String(255), index=True)
    search_oe_norm: Mapped[str] = mapped_column(String(255), index=True)
    extracted_oe_norms: Mapped[list[str]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    verified_matched_oe_norm: Mapped[str | None] = mapped_column(
        String(255), index=True
    )
    comparison_identity_key: Mapped[str | None] = mapped_column(String(255), index=True)
    oe_verification_status: Mapped[str] = mapped_column(
        String(32), default="UNKNOWN", server_default="UNKNOWN", index=True
    )
    oe_evidence: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    oe_extractor_version: Mapped[str] = mapped_column(
        String(80),
        default="legacy-unverified-v0",
        server_default="legacy-unverified-v0",
    )
    oe_reenriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    oe_reenrichment_error_code: Mapped[str | None] = mapped_column(String(100))
    canonical_category_id: Mapped[str] = mapped_column(
        String(120), default="generic_unknown", server_default="generic_unknown"
    )
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3))
    currency_raw: Mapped[str | None] = mapped_column(String(32))
    currency_inferred: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    is_available: Mapped[bool | None] = mapped_column(Boolean)
    match_confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    source_confidence: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), default=Decimal("0"), server_default="0"
    )
    source_confidence_factors: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
    source_confidence_method_version: Mapped[str] = mapped_column(
        String(80),
        default="legacy-unverified-v0",
        server_default="legacy-unverified-v0",
    )
    parser_version: Mapped[str] = mapped_column(String(80))
    evidence_contract_version: Mapped[str] = mapped_column(
        String(80), default="comparison-evidence-v2", server_default="legacy-unknown-v0"
    )
    comparability_policy_id: Mapped[str | None] = mapped_column(String(120))
    comparability_policy_hash: Mapped[str | None] = mapped_column(String(64))
    comparison_evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    comparability_hard_gate_result: Mapped[str] = mapped_column(
        String(32), default="MANUAL_REVIEW", server_default="MANUAL_REVIEW"
    )
    calibration_exclusion_codes: Mapped[list[str]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    seller_identity_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    source_provenance_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    automatic_eligible: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", index=True
    )
    via_cross: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", index=True
    )
    cross_link_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cross_links.id", ondelete="RESTRICT"), index=True
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OfferProcessingOutcome(Base):
    """Append-only terminal partition for every retrieved candidate element."""

    __tablename__ = "offer_processing_outcomes"
    __table_args__ = (
        UniqueConstraint(
            "raw_market_capture_id",
            "pricing_run_item_id",
            "raw_offer_index",
            name="uq_offer_processing_outcome_capture_item_index",
        ),
        CheckConstraint("raw_offer_index >= 0", name="ck_offer_outcome_index"),
        CheckConstraint(
            "outcome_code IN ('OBSERVATION_PERSISTED', 'REJECTED_NOT_MAPPING', "
            "'REJECTED_INVALID_PRICE', 'REJECTED_INVALID_MATCH_SCORE', "
            "'REJECTED_MISSING_LISTING_IDENTITY', 'REJECTED_SCHEMA_MISMATCH', "
            "'REJECTED_SERIALIZATION', 'FAILED_INTERNAL_PROCESSING')",
            name="ck_offer_outcome_code",
        ),
        CheckConstraint(
            "((outcome_code = 'OBSERVATION_PERSISTED' AND market_observation_id IS NOT NULL) "
            "OR (outcome_code <> 'OBSERVATION_PERSISTED' AND market_observation_id IS NULL))",
            name="ck_offer_outcome_observation_binding",
        ),
        Index("ix_offer_outcome_item_code", "pricing_run_item_id", "outcome_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    pricing_run_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pricing_run_items.id", ondelete="CASCADE"), index=True
    )
    raw_market_capture_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("raw_market_captures.id", ondelete="CASCADE"), index=True
    )
    market_observation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("market_observations.id", ondelete="RESTRICT"), index=True
    )
    source_listing_id: Mapped[str | None] = mapped_column(String(255))
    raw_offer_index: Mapped[int] = mapped_column(Integer)
    outcome_code: Mapped[str] = mapped_column(String(64))
    stage: Mapped[str] = mapped_column(String(40))
    reason_codes: Mapped[list[str]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    payload_sha256: Mapped[str | None] = mapped_column(String(64))
    safe_sample: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CrossLink(Base):
    """Append-only canonical Stage A+B decision for one normalized OE pair."""

    __tablename__ = "cross_links"
    __table_args__ = (
        UniqueConstraint(
            "pricing_run_id",
            "our_oem_norm",
            "extracted_oem_norm",
            name="uq_cross_link_run_pair",
        ),
        UniqueConstraint("sequence_no", name="uq_cross_link_sequence"),
        CheckConstraint(
            "our_oem_norm <> '' AND extracted_oem_norm <> '' "
            "AND our_oem_norm <> extracted_oem_norm",
            name="ck_cross_link_distinct_oems",
        ),
        CheckConstraint(
            "validation_status IN ('CONFIRMED', 'REVIEW', 'REJECTED', 'UNKNOWN')",
            name="ck_cross_link_validation_status",
        ),
        CheckConstraint(
            "(validation_status = 'REJECTED' AND rejection_reason IS NOT NULL) OR "
            "(validation_status <> 'REJECTED' AND rejection_reason IS NULL)",
            name="ck_cross_link_rejection_reason",
        ),
        Index(
            "ix_cross_link_workspace_pair",
            "workspace_id",
            "our_oem_norm",
            "extracted_oem_norm",
        ),
        Index(
            "ix_cross_link_run_status",
            "pricing_run_id",
            "validation_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    sequence_no: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), index=True
    )
    pricing_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pricing_runs.id", ondelete="RESTRICT"), index=True
    )
    catalog_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_items.id", ondelete="RESTRICT"), index=True
    )
    our_oem_norm: Mapped[str] = mapped_column(String(255))
    extracted_oem_norm: Mapped[str] = mapped_column(String(255))
    source_listing_url: Mapped[str] = mapped_column(Text)
    source_seller: Mapped[str] = mapped_column(String(255))
    raw_context: Mapped[str] = mapped_column(Text)
    extraction_method: Mapped[str] = mapped_column(String(50))
    validation_status: Mapped[str] = mapped_column(String(16))
    rejection_reason: Mapped[str | None] = mapped_column(String(50))
    reciprocal_evidence_url: Mapped[str | None] = mapped_column(Text)
    source_evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    validation_details: Mapped[dict[str, Any]] = mapped_column(JSON)
    method_version: Mapped[str] = mapped_column(String(80))
    config_sha256: Mapped[str] = mapped_column(String(64))
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ObservationTierClassification(Base):
    __tablename__ = "observation_tier_classifications"
    __table_args__ = (
        CheckConstraint(
            "tier IN ('oem', 'oes', 'aftermarket_a', 'aftermarket_b', "
            "'budget', 'kemp', 'used', 'unknown')",
            name="ck_observation_tier",
        ),
        CheckConstraint(
            "tier_confidence >= 0 AND tier_confidence <= 1",
            name="ck_observation_tier_confidence",
        ),
        CheckConstraint(
            "cohort_role IN ('TARGET_MARKET', 'KEMP_REFERENCE', 'OWNED_STORE', "
            "'USED_REJECTED', 'DUMPING_DIAGNOSTIC', 'MANUAL_REVIEW', "
            "'HARD_REJECTED')",
            name="ck_observation_cohort_role",
        ),
        Index(
            "ix_observation_tier_current",
            "market_observation_id",
            "classified_at",
            "id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    market_observation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("market_observations.id", ondelete="CASCADE"), index=True
    )
    tier: Mapped[str] = mapped_column(String(24))
    tier_confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    is_used: Mapped[bool] = mapped_column(Boolean)
    is_kemp: Mapped[bool] = mapped_column(Boolean)
    is_owned: Mapped[bool] = mapped_column(Boolean)
    is_dumping: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    cohort_role: Mapped[str] = mapped_column(
        String(32), default="MANUAL_REVIEW", server_default="MANUAL_REVIEW"
    )
    exclusion_reason: Mapped[str | None] = mapped_column(String(100))
    reason_codes: Mapped[list[str]] = mapped_column(JSON)
    method_version: Mapped[str] = mapped_column(String(80))
    override_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    classified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BrandTierRule(TimestampMixin, Base):
    __tablename__ = "brand_tier_rules"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "brand_normalized",
            "version",
            name="uq_brand_tier_rule_version",
        ),
        CheckConstraint(
            "tier IN ('oem', 'oes', 'aftermarket_a', 'aftermarket_b', "
            "'budget', 'kemp', 'used', 'unknown')",
            name="ck_brand_tier_rule_tier",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    brand_normalized: Mapped[str] = mapped_column(String(255), index=True)
    tier: Mapped[str] = mapped_column(String(24))
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    version: Mapped[str] = mapped_column(String(80))
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )


class TierCalibrationPairRecord(Base):
    """Append-only independent paired-OE unit used by a pricing run."""

    __tablename__ = "tier_calibration_pairs"
    __table_args__ = (
        UniqueConstraint(
            "pricing_run_id",
            "category",
            "tier",
            "oe_norm",
            name="uq_tier_calibration_pair_run_unit",
        ),
        CheckConstraint("tier_price > 0", name="ck_tier_calibration_tier_price"),
        CheckConstraint(
            "reference_price > 0", name="ck_tier_calibration_reference_price"
        ),
        CheckConstraint(
            "quality_weight > 0 AND quality_weight <= 1",
            name="ck_tier_calibration_quality_weight",
        ),
        CheckConstraint(
            "tier IN ('oem', 'oes', 'aftermarket_a', 'aftermarket_b')",
            name="ck_tier_calibration_tier",
        ),
        Index(
            "ix_tier_calibration_run_category_tier",
            "pricing_run_id",
            "category",
            "tier",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    pricing_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pricing_runs.id", ondelete="CASCADE"), index=True
    )
    oe_norm: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(255))
    tier: Mapped[str] = mapped_column(String(24))
    tier_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    reference_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    quality_weight: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    tier_observation_ids: Mapped[list[str]] = mapped_column(JSON)
    reference_observation_ids: Mapped[list[str]] = mapped_column(JSON)
    identity_evidence: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    dataset_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TierCoefficientRecord(Base):
    __tablename__ = "tier_coefficients"
    __table_args__ = (
        Index(
            "uq_tier_coefficient_run_scope_version",
            "workspace_id",
            "pricing_run_id",
            "category",
            "tier",
            "model",
            "coefficient_version",
            unique=True,
            postgresql_where=text("pricing_run_id IS NOT NULL"),
        ),
        Index(
            "uq_tier_coefficient_global_scope_version",
            "workspace_id",
            "category",
            "tier",
            "model",
            "coefficient_version",
            unique=True,
            postgresql_where=text("pricing_run_id IS NULL"),
        ),
        CheckConstraint("multiplier > 0", name="ck_tier_coefficient_positive"),
        CheckConstraint(
            "sample_size >= 0", name="ck_tier_coefficient_sample_nonnegative"
        ),
        CheckConstraint(
            "effective_sample_size >= 0",
            name="ck_tier_coefficient_effective_sample_nonnegative",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_tier_coefficient_confidence",
        ),
        Index(
            "ix_tier_coefficient_lookup",
            "workspace_id",
            "category",
            "tier",
            "validated",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    pricing_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pricing_runs.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(255))
    tier: Mapped[str] = mapped_column(String(24))
    model: Mapped[str] = mapped_column(String(32))
    multiplier: Mapped[Decimal] = mapped_column(Numeric(18, 10))
    log_effect: Mapped[Decimal] = mapped_column(Numeric(18, 10))
    global_log_effect: Mapped[Decimal | None] = mapped_column(Numeric(18, 10))
    shrinkage_weight: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    sample_size: Mapped[int] = mapped_column(Integer)
    effective_sample_size: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    interval_low: Mapped[Decimal | None] = mapped_column(Numeric(18, 10))
    interval_high: Mapped[Decimal | None] = mapped_column(Numeric(18, 10))
    validated: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    dataset_hash: Mapped[str] = mapped_column(String(64))
    method_version: Mapped[str] = mapped_column(String(80))
    coefficient_version: Mapped[str] = mapped_column(String(160))
    policy_version: Mapped[str] = mapped_column(String(80))
    validation_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_selected: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PricingRecommendation(Base):
    __tablename__ = "pricing_recommendations"
    __table_args__ = (
        UniqueConstraint(
            "pricing_run_item_id", name="uq_pricing_recommendation_run_item"
        ),
        CheckConstraint(
            "action IN ('RAISE', 'HOLD', 'LOWER', 'MANUAL_REVIEW', 'INSUFFICIENT_DATA')",
            name="ck_pricing_recommendation_action",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_pricing_recommendation_confidence",
        ),
        CheckConstraint(
            "current_price > 0", name="ck_pricing_recommendation_current_price"
        ),
        CheckConstraint(
            "raw_competitor_count >= 0 AND unique_seller_count >= 0 AND "
            "clean_competitor_count >= 0 AND outlier_count >= 0",
            name="ck_pricing_recommendation_counts_nonnegative",
        ),
        CheckConstraint(
            "target_market_count >= 0 AND kemp_reference_count >= 0 AND "
            "owned_store_count >= 0 AND rejected_count >= 0",
            name="ck_pricing_recommendation_cohort_counts_nonnegative",
        ),
        CheckConstraint(
            "(recommended_price IS NULL AND absolute_recommended_change IS NULL "
            "AND percentage_recommended_change IS NULL) OR "
            "(recommended_price IS NOT NULL AND absolute_recommended_change >= 0 "
            "AND percentage_recommended_change >= 0)",
            name="ck_pricing_recommendation_change_metrics",
        ),
        CheckConstraint(
            "action NOT IN ('RAISE', 'LOWER') OR "
            "(action_gates_passed AND recommended_price IS NOT NULL)",
            name="ck_pricing_recommendation_action_gate",
        ),
        CheckConstraint(
            "(action <> 'RAISE' OR recommended_price > current_price) AND "
            "(action <> 'LOWER' OR recommended_price < current_price)",
            name="ck_pricing_recommendation_direction",
        ),
        CheckConstraint(
            "verified_seller_count >= 0",
            name="ck_pricing_recommendation_verified_sellers",
        ),
        CheckConstraint(
            "NOT automatic_eligible OR (action_gates_passed AND "
            "action IN ('RAISE', 'HOLD', 'LOWER') AND "
            "comparability_policy_id IS NOT NULL AND "
            "comparability_policy_hash IS NOT NULL AND "
            "char_length(comparability_policy_hash) = 64 AND "
            "decision_fingerprint IS NOT NULL AND "
            "char_length(decision_fingerprint) = 64)",
            name="ck_pricing_recommendation_auto_evidence",
        ),
        Index("ix_pricing_recommendation_run_action", "pricing_run_id", "action"),
        Index(
            "ix_pricing_recommendation_run_priority", "pricing_run_id", "priority_score"
        ),
        Index(
            "ix_pricing_recommendation_run_absolute_change",
            "pricing_run_id",
            "absolute_recommended_change",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    pricing_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pricing_runs.id", ondelete="CASCADE"), index=True
    )
    pricing_run_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pricing_run_items.id", ondelete="CASCADE"), index=True
    )
    catalog_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_items.id", ondelete="CASCADE"), index=True
    )
    catalog_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_import_batches.id", ondelete="RESTRICT"), index=True
    )
    context_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    calculation_trace: Mapped[dict[str, Any]] = mapped_column(JSON)
    action: Mapped[str] = mapped_column(String(24))
    current_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    fair_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    recommended_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    lower_bound: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    upper_bound: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    confidence_grade: Mapped[str] = mapped_column(String(16))
    weakest_factor: Mapped[str | None] = mapped_column(String(50))
    factor_scores: Mapped[dict[str, Any]] = mapped_column(JSON)
    competitor_count: Mapped[int] = mapped_column(Integer)
    raw_competitor_count: Mapped[int] = mapped_column(Integer)
    unique_seller_count: Mapped[int] = mapped_column(Integer)
    clean_competitor_count: Mapped[int] = mapped_column(Integer)
    target_market_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    kemp_reference_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    owned_store_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    rejected_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    effective_competitor_count: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    dispersion: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    outlier_method: Mapped[str] = mapped_column(String(24))
    outlier_count: Mapped[int] = mapped_column(Integer)
    sensitivity: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    action_gates_passed: Mapped[bool] = mapped_column(Boolean)
    automatic_eligible: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    verified_seller_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    comparability_policy_id: Mapped[str | None] = mapped_column(String(120))
    comparability_policy_hash: Mapped[str | None] = mapped_column(String(64))
    decision_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    hard_gate_trace: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
    robust_diagnostic: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    cost_floor: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    cost_basis_inventory_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    priority_score: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    priority_score_type: Mapped[str] = mapped_column(String(40))
    review_priority: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    absolute_recommended_change: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    percentage_recommended_change: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 10)
    )
    reason_codes: Mapped[list[str]] = mapped_column(JSON)
    evidence_observation_ids: Mapped[list[str]] = mapped_column(JSON)
    kemp_reference_observation_ids: Mapped[list[str]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    excluded_observations: Mapped[list[dict[str, str]]] = mapped_column(JSON)
    policy_version: Mapped[str] = mapped_column(String(80))
    parser_version: Mapped[str] = mapped_column(String(80))
    classifier_version: Mapped[str] = mapped_column(String(80))
    coefficient_version: Mapped[str | None] = mapped_column(String(160))
    calibration_dataset_hash: Mapped[str | None] = mapped_column(String(64))
    currency: Mapped[str] = mapped_column(String(3))
    price_tick: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    price_tick_version: Mapped[str] = mapped_column(String(80))
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RecommendationDecision(Base):
    __tablename__ = "recommendation_decisions"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('accepted', 'rejected', 'overridden')",
            name="ck_recommendation_decision",
        ),
        CheckConstraint(
            "NOT allow_below_cost OR "
            "(warning_confirmed AND warning_confirmed_at IS NOT NULL)",
            name="ck_recommendation_decision_below_cost_confirmation",
        ),
        Index(
            "ix_recommendation_decision_recommendation_time",
            "recommendation_id",
            "decided_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    recommendation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pricing_recommendations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    decision: Mapped[str] = mapped_column(String(16))
    old_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    new_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    cost_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    recommended_price_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    approved_floor: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    allow_below_cost: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    reason: Mapped[str] = mapped_column(Text)
    warning_confirmed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    warning_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    context_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    policy_version: Mapped[str] = mapped_column(String(80))
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
