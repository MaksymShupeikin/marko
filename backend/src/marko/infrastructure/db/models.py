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

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    firebase_uid: Mapped[str | None] = mapped_column(
        String(128), unique=True, index=True
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(160))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )


class Workspace(TimestampMixin, Base):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160))
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)


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
    scrape_deadline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    scrape_owner_task_id: Mapped[str | None] = mapped_column(
        String(255),
        index=True,
    )
    scrape_lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
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
    scrape_evidence_coverage: Mapped[Decimal | None] = mapped_column(
        Numeric(7, 6)
    )
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
            "AND memory_peak_bytes >= 0",
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
    )
    task_id: Mapped[str | None] = mapped_column(String(255), index=True)
    execution_no: Mapped[int] = mapped_column(Integer)
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
            "structured_completeness >= 0 "
            "AND structured_completeness <= 1",
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
            "NOT allow_below_cost OR (stock_status = 'dead_stock' AND "
            "below_cost_floor IS NOT NULL AND below_cost_warning_confirmed)",
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
            "AND max_task_executions > 0",
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
        Index("ix_scrape_target_run_status", "pricing_run_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    pricing_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pricing_runs.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(
        String(50), default="prom", server_default="prom"
    )
    original_url: Mapped[str | None] = mapped_column(Text)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    product_key: Mapped[str | None] = mapped_column(String(100))
    query: Mapped[str] = mapped_column(String(255))
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    adapter_version: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(
        String(24), default="queued", server_default="queued"
    )
    owner_task_id: Mapped[str | None] = mapped_column(String(255), index=True)
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
    first_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
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
            "AND memory_peak_bytes >= 0",
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
    network_attempted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    status: Mapped[str] = mapped_column(
        String(24), default="running", server_default="running"
    )
    error_category: Mapped[str | None] = mapped_column(String(50))
    error_detail: Mapped[str | None] = mapped_column(Text)
    wall_time_ms: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0"
    )
    cpu_time_ms: Mapped[int] = mapped_column(
        BigInteger, default=0, server_default="0"
    )
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
        Index("ix_market_observation_catalog_time", "catalog_item_id", "observed_at"),
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
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    brand_raw: Mapped[str | None] = mapped_column(String(255))
    matched_oe_norm: Mapped[str] = mapped_column(String(255), index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3))
    is_available: Mapped[bool | None] = mapped_column(Boolean)
    match_confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    source_confidence: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), default=Decimal("1"), server_default="1"
    )
    parser_version: Mapped[str] = mapped_column(String(80))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


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
            "action NOT IN ('RAISE', 'LOWER') OR "
            "(action_gates_passed AND recommended_price IS NOT NULL)",
            name="ck_pricing_recommendation_action_gate",
        ),
        CheckConstraint(
            "(action <> 'RAISE' OR recommended_price > current_price) AND "
            "(action <> 'LOWER' OR recommended_price < current_price)",
            name="ck_pricing_recommendation_direction",
        ),
        Index("ix_pricing_recommendation_run_action", "pricing_run_id", "action"),
        Index(
            "ix_pricing_recommendation_run_priority", "pricing_run_id", "priority_score"
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
    effective_competitor_count: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    dispersion: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    outlier_method: Mapped[str] = mapped_column(String(24))
    outlier_count: Mapped[int] = mapped_column(Integer)
    sensitivity: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    action_gates_passed: Mapped[bool] = mapped_column(Boolean)
    cost_floor: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    cost_basis_inventory_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    priority_score: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    priority_score_type: Mapped[str] = mapped_column(String(40))
    review_priority: Mapped[Decimal] = mapped_column(Numeric(20, 6))
    reason_codes: Mapped[list[str]] = mapped_column(JSON)
    evidence_observation_ids: Mapped[list[str]] = mapped_column(JSON)
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
