"""Relational persistence models for accounts, listings, prices, and matches."""

from __future__ import annotations

import enum
import hashlib
import json
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    JSON,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
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
        Index(
            "ix_listings_owned_catalog_identity",
            "catalog_identity_kind",
            "catalog_identity_value",
            "store_id",
        ),
        Index("ix_listings_owned_catalog_sku_norm", "catalog_sku_norm"),
        Index("ix_listings_owned_catalog_oe_norm", "catalog_oe_norm"),
        Index(
            "ix_listings_catalog_internal_code_norm",
            "catalog_internal_code_norm",
            postgresql_where=text("catalog_internal_code_norm <> ''"),
        ),
        Index("ix_listings_owned_catalog_name_lower", text("lower(name)")),
        Index("ix_listings_owned_catalog_store_first", "store_id", "name", "id"),
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
    catalog_identity_kind: Mapped[str] = mapped_column(
        Text,
        Computed(
            "public.marko_catalog_identity_kind("
            "brand, sku, model_id, raw_data ->> 'oe_raw')",
            persisted=True,
        ),
    )
    catalog_identity_value: Mapped[str] = mapped_column(
        Text,
        Computed(
            "public.marko_catalog_identity_value("
            "brand, sku, model_id, raw_data ->> 'oe_raw', store_id, id)",
            persisted=True,
        ),
    )
    catalog_sku_norm: Mapped[str] = mapped_column(
        Text,
        Computed("public.marko_catalog_normalize(sku)", persisted=True),
    )
    catalog_oe_norm: Mapped[str] = mapped_column(
        Text,
        Computed(
            "public.marko_catalog_normalize(raw_data ->> 'oe_raw')",
            persisted=True,
        ),
    )
    catalog_model_norm: Mapped[str] = mapped_column(
        Text,
        Computed("public.marko_catalog_normalize(model_id)", persisted=True),
    )
    catalog_internal_code_norm: Mapped[str] = mapped_column(
        Text,
        Computed(
            "public.marko_listing_internal_code(raw_data)",
            persisted=True,
        ),
    )
    catalog_internal_code_count: Mapped[int] = mapped_column(
        SmallInteger,
        Computed(
            "public.marko_listing_internal_code_count(raw_data)",
            persisted=True,
        ),
    )
    catalog_brand_norm: Mapped[str] = mapped_column(
        Text,
        Computed("public.marko_catalog_normalize(brand)", persisted=True),
    )
    catalog_name_norm: Mapped[str] = mapped_column(
        Text,
        Computed("public.marko_catalog_normalize(name)", persisted=True),
    )
    catalog_description_norm: Mapped[str] = mapped_column(
        Text,
        Computed(
            "public.marko_catalog_normalize(raw_data ->> 'description')",
            persisted=True,
        ),
    )
    catalog_completeness: Mapped[int] = mapped_column(
        SmallInteger,
        Computed(
            "("
            "CASE WHEN btrim(coalesce(raw_data ->> 'image', '')) "
            "LIKE 'http://%' OR "
            "btrim(coalesce(raw_data ->> 'image', '')) LIKE 'https://%' "
            "THEN 1 ELSE 0 END"
            " + CASE WHEN brand IS NOT NULL AND brand <> '' THEN 1 ELSE 0 END"
            " + CASE WHEN sku IS NOT NULL AND sku <> '' THEN 1 ELSE 0 END"
            " + CASE WHEN current_price IS NOT NULL THEN 1 ELSE 0 END"
            " + CASE WHEN is_available IS NOT NULL THEN 1 ELSE 0 END"
            " + CASE WHEN model_id IS NOT NULL AND model_id <> '' "
            "THEN 1 ELSE 0 END"
            ")",
            persisted=True,
        ),
    )
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


class CatalogDiscoveryRun(Base):
    """One bounded live Prom discovery initiated from an owned catalog card."""

    __tablename__ = "catalog_discovery_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'failed')",
            name="ck_catalog_discovery_run_status",
        ),
        CheckConstraint(
            "request_count >= 0 AND retrieved_count >= 0 "
            "AND persisted_count >= 0 AND rejected_count >= 0 "
            "AND owned_excluded_count >= 0 AND pricing_evidence_count >= 0 "
            "AND reference_only_count >= 0 AND rejected_candidate_count >= 0 "
            "AND unfetched_count >= 0 AND search_page_limit > 0",
            name="ck_catalog_discovery_run_counts",
        ),
        CheckConstraint(
            "reference_price IS NULL OR reference_price > 0",
            name="ck_catalog_discovery_run_reference_price",
        ),
        CheckConstraint(
            "coverage_ratio IS NULL OR (coverage_ratio >= 0 AND coverage_ratio <= 1)",
            name="ck_catalog_discovery_run_coverage_ratio",
        ),
        Index(
            "ix_catalog_discovery_workspace_product_time",
            "workspace_id",
            "product_key",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    product_key: Mapped[str] = mapped_column(String(64), index=True)
    query: Mapped[str] = mapped_column(String(255))
    sku: Mapped[str | None] = mapped_column(String(255))
    oe_norm: Mapped[str | None] = mapped_column(String(255), index=True)
    brand: Mapped[str | None] = mapped_column(String(255))
    reference_title: Mapped[str | None] = mapped_column(Text)
    reference_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    reference_currency: Mapped[str | None] = mapped_column(String(3))
    reference_category: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(16), default="running", server_default="running", index=True
    )
    parser_outcome: Mapped[str | None] = mapped_column(String(40))
    prom_reported_total: Mapped[int | None] = mapped_column(Integer)
    request_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    retrieved_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    persisted_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    rejected_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    owned_excluded_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    pricing_evidence_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    reference_only_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    rejected_candidate_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    search_page_limit: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1"
    )
    unfetched_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    coverage_ratio: Mapped[Decimal | None] = mapped_column(Numeric(7, 6))
    coverage_reason: Mapped[str | None] = mapped_column(String(64))
    selection_method_version: Mapped[str | None] = mapped_column(String(80))
    selection_config_sha256: Mapped[str | None] = mapped_column(String(64))
    brand_rules_dataset_id: Mapped[str | None] = mapped_column(String(255))
    brand_rules_sha256: Mapped[str | None] = mapped_column(String(64))
    selection_histogram: Mapped[dict[str, int]] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CatalogDiscoveryCapture(Base):
    """Immutable raw HTTP capture referenced by an owned-catalog discovery."""

    __tablename__ = "catalog_discovery_captures"
    __table_args__ = (
        UniqueConstraint(
            "discovery_run_id",
            "sequence_no",
            name="uq_catalog_discovery_capture_sequence",
        ),
        CheckConstraint(
            "sequence_no > 0 AND attempts_total > 0 AND latency_ms >= 0 "
            "AND raw_size_bytes >= 0",
            name="ck_catalog_discovery_capture_measurements",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    discovery_run_id: Mapped[uuid.UUID] = mapped_column(
        # RESTRICT, not CASCADE: a capture binds an evidence blob to the request
        # that produced it. Deleting the run would leave the blob unattributable
        # even though the blob itself is protected (F2-0014).
        ForeignKey("catalog_discovery_runs.id", ondelete="RESTRICT"),
        index=True,
    )
    evidence_blob_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("scrape_evidence_blobs.id", ondelete="RESTRICT"), index=True
    )
    sequence_no: Mapped[int] = mapped_column(Integer)
    request_kind: Mapped[str] = mapped_column(String(40))
    prepared_url: Mapped[str] = mapped_column(Text)
    status_code: Mapped[int] = mapped_column(Integer)
    attempts_total: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(BigInteger)
    raw_size_bytes: Mapped[int] = mapped_column(BigInteger)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CatalogDiscoveryOffer(Base):
    """A parsed discovery candidate, kept separate from pricing evidence."""

    __tablename__ = "catalog_discovery_offers"
    __table_args__ = (
        UniqueConstraint(
            "discovery_run_id",
            "source_listing_id",
            name="uq_catalog_discovery_offer_listing",
        ),
        CheckConstraint(
            "raw_offer_index >= 0 AND sale_price > 0 "
            "AND (reference_price IS NULL OR reference_price > 0) "
            "AND source_confidence >= 0 AND source_confidence <= 1",
            name="ck_catalog_discovery_offer_values",
        ),
        CheckConstraint(
            "reference_price IS NULL OR sale_price <= reference_price",
            name="ck_catalog_discovery_offer_sale_not_above_reference",
        ),
        CheckConstraint(
            "identity_status IN ('QUERY_TOKEN_PRESENT', 'SEARCH_RESULT_UNVERIFIED')",
            name="ck_catalog_discovery_offer_identity_status",
        ),
        CheckConstraint(
            "selection_status IN ('PRICING_EVIDENCE', 'REFERENCE_ONLY', 'REJECTED')",
            name="ck_catalog_discovery_offer_selection_status",
        ),
        CheckConstraint(
            "tier_confidence >= 0 AND tier_confidence <= 1",
            name="ck_catalog_discovery_offer_tier_confidence",
        ),
        Index(
            "ix_catalog_discovery_offer_run_owned",
            "discovery_run_id",
            "is_owned",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    discovery_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_discovery_runs.id", ondelete="CASCADE"), index=True
    )
    raw_offer_index: Mapped[int] = mapped_column(Integer)
    source_listing_id: Mapped[str] = mapped_column(String(255))
    seller_id: Mapped[str] = mapped_column(String(255))
    seller_name: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    sku: Mapped[str | None] = mapped_column(String(255))
    brand: Mapped[str | None] = mapped_column(String(255))
    sale_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    reference_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3))
    measure_unit: Mapped[str | None] = mapped_column(String(80))
    is_available: Mapped[bool | None] = mapped_column(Boolean)
    is_owned: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", index=True
    )
    title_contains_query: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    identity_status: Mapped[str] = mapped_column(String(40))
    source_confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    reason_codes: Mapped[list[str]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    selection_status: Mapped[str] = mapped_column(
        String(24),
        default="REFERENCE_ONLY",
        server_default="REFERENCE_ONLY",
        index=True,
    )
    selection_reason: Mapped[str] = mapped_column(
        String(100),
        default="LEGACY_UNCLASSIFIED",
        server_default="LEGACY_UNCLASSIFIED",
    )
    passed_gates: Mapped[list[str]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    selection_flags: Mapped[list[str]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    selection_details: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
    predicted_tier: Mapped[str] = mapped_column(
        String(32), default="unknown", server_default="unknown"
    )
    tier_confidence: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), default=Decimal("0"), server_default="0"
    )
    raw_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
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
        UniqueConstraint(
            "workspace_id",
            "request_fingerprint",
            name="uq_catalog_import_workspace_fingerprint",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'partial', 'failed')",
            name="ck_catalog_import_batch_status",
        ),
        CheckConstraint(
            "(row_outcomes_contract_version IS NULL AND "
            "row_outcomes_sha256 IS NULL) OR "
            "(row_outcomes_contract_version = 'catalog-row-outcomes-v1' AND "
            "char_length(row_outcomes_sha256) = 64 AND "
            "json_array_length(row_outcomes) = total_rows)",
            name="ck_catalog_import_row_outcomes_contract",
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
    request_fingerprint: Mapped[str | None] = mapped_column(String(64))
    content_size: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(16), default="queued", server_default="queued"
    )
    column_mapping: Mapped[dict[str, Any]] = mapped_column(JSON)
    total_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    imported_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    rejected_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_log: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    row_outcomes_contract_version: Mapped[str | None] = mapped_column(String(48))
    row_outcomes_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    row_outcomes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        default=list,
        server_default="[]",
    )
    # Frequency of every characteristic name the workbook carried, split into
    # recognized and unrecognized, plus extraction anomalies.  A seller renaming
    # a field has to show up as a number here instead of as missing identity.
    characteristics_report: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
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
        CheckConstraint(
            "identity_status IN ('OE_CONFIRMED', 'MPN_ONLY', 'UNRESOLVED')",
            name="ck_catalog_item_identity_status",
        ),
        # After WP-2 an OE_CONFIRMED row must actually carry the OE; without
        # this the status can drift away from the column it describes.
        CheckConstraint(
            "identity_status <> 'OE_CONFIRMED' OR "
            "(oe_norm IS NOT NULL AND oe_norm <> '')",
            name="ck_catalog_item_identity_oe_present",
        ),
        Index("ix_catalog_item_workspace_oe", "workspace_id", "oe_norm"),
        Index("ix_catalog_item_workspace_mpn", "workspace_id", "mpn_norm"),
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
    #: Наш собственный код позиции. По нему каталог связывается с тем, что
    #: напарсено с витрины: артикул принадлежит площадке, OE — детали, и только
    #: этот код принадлежит нам. Индексируется, потому что связь идёт по нему.
    internal_code_raw: Mapped[str] = mapped_column(Text, default="", server_default="")
    internal_code_norm: Mapped[str] = mapped_column(
        String(255), default="", server_default="", index=True
    )
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
    # Identity read out of the Prom characteristics block.  ``part_numbers_norm``
    # is the seller's own cross list and is what breaks the deadlock where a
    # confirmed cross could only ever come from an observation that itself
    # required a confirmed cross to be collected.
    part_numbers_raw: Mapped[list[str]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    part_numbers_norm: Mapped[list[str]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    applicability_brands: Mapped[list[str]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    applicability_models: Mapped[list[str]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    characteristics_raw: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
    # WP-2: which of the already-existing ``oe_*`` / ``mpn_*`` pairs above was
    # actually decided, and on what grounds.  An empty ``oe_norm`` is ambiguous
    # on its own — it can mean "the brand says this article is a supplier
    # number" or "nobody has looked yet" — and the difference decides whether
    # the position belongs in a review queue.  ``UNRESOLVED`` is the state of
    # every row imported before this revision, until the WP-6 reparse.
    identity_status: Mapped[str] = mapped_column(
        String(20), default="UNRESOLVED", server_default="UNRESOLVED"
    )
    identity_reason: Mapped[str | None] = mapped_column(String(40))


class CatalogProduct(TimestampMixin, Base):
    """Stable workspace product fed by a store listing or an XLSX row.

    ``Listing`` and ``CatalogItem`` remain immutable/source-specific evidence.
    This row is the current product a person recognises in the UI and therefore
    survives repeated store synchronisations and replacement XLSX imports.
    """

    __tablename__ = "catalog_products"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "source_kind",
            "source_id",
            "source_product_id",
            name="uq_catalog_product_source_identity",
        ),
        CheckConstraint(
            "source_kind IN ('PROM_STORE', 'XLSX')",
            name="ck_catalog_product_source_kind",
        ),
        CheckConstraint(
            "identity_status IN ('VERIFIED_EXACT', 'VERIFIED_CROSS', "
            "'AMBIGUOUS', 'UNRESOLVED', 'CONFLICT')",
            name="ck_catalog_product_identity_status",
        ),
        CheckConstraint(
            "current_price IS NULL OR current_price > 0",
            name="ck_catalog_product_price_positive",
        ),
        Index("ix_catalog_product_workspace_status", "workspace_id", "identity_status"),
        Index("ix_catalog_product_workspace_oe", "workspace_id", "oe_norm"),
        Index("ix_catalog_product_workspace_name", "workspace_id", "name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    source_kind: Mapped[str] = mapped_column(String(20))
    # A generic UUID on purpose: for PROM_STORE this is marketplace_stores.id;
    # for XLSX it is a stable UUID derived from workspace and filename. Source
    # evidence has its own FK.
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    source_product_id: Mapped[str] = mapped_column(String(255))
    listing_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("listings.id", ondelete="SET NULL"), index=True
    )
    catalog_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog_items.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(Text)
    sku: Mapped[str | None] = mapped_column(String(255))
    internal_code: Mapped[str | None] = mapped_column(String(255))
    oe_raw: Mapped[str | None] = mapped_column(Text)
    oe_norm: Mapped[str | None] = mapped_column(String(255))
    mpn_raw: Mapped[str | None] = mapped_column(Text)
    mpn_norm: Mapped[str | None] = mapped_column(String(255))
    brand: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    product_url: Mapped[str | None] = mapped_column(Text)
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(
        String(3), default="UAH", server_default="UAH"
    )
    is_available: Mapped[bool | None] = mapped_column(Boolean)
    identity_status: Mapped[str] = mapped_column(
        String(24), default="UNRESOLVED", server_default="UNRESOLVED"
    )
    identity_reason: Mapped[str | None] = mapped_column(String(80))
    raw_data: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CatalogReferenceItem(Base):
    """Reference-only identity assertion imported from workbook ``Только код``."""

    __tablename__ = "catalog_reference_items"
    __table_args__ = (
        UniqueConstraint(
            "import_batch_id",
            "source_sheet",
            "source_row",
            name="uq_catalog_reference_batch_sheet_row",
        ),
        CheckConstraint(
            "char_length(content_sha256) = 64",
            name="ck_catalog_reference_content_sha256",
        ),
        Index(
            "ix_catalog_reference_workspace_internal_code",
            "workspace_id",
            "internal_code_norm",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    import_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_import_batches.id", ondelete="CASCADE"), index=True
    )
    source_sheet: Mapped[str] = mapped_column(String(255))
    source_row: Mapped[int] = mapped_column(Integer)
    internal_code_raw: Mapped[str] = mapped_column(Text, default="", server_default="")
    internal_code_norm: Mapped[str] = mapped_column(
        String(255), default="", server_default=""
    )
    original_raw: Mapped[str] = mapped_column(Text, default="", server_default="")
    original_norm: Mapped[str] = mapped_column(
        String(255), default="", server_default=""
    )
    title: Mapped[str | None] = mapped_column(Text)
    oe_sources: Mapped[list[Any]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    confirmed_numbers: Mapped[list[Any]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    anomalies: Mapped[list[Any]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    evidence_url: Mapped[str | None] = mapped_column(Text)
    raw_row: Mapped[dict[str, Any]] = mapped_column(JSON)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CatalogKempLinkResolution(Base):
    """Append-only terminal resolution of one canonical item against owned cards."""

    __tablename__ = "catalog_kemp_link_resolutions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('LINKED_OWNED_LISTING_GROUP', 'KEMP_CODE_MISSING', "
            "'NO_CURRENT_OWNED_LISTING', 'AMBIGUOUS_LISTING_INTERNAL_CODES', "
            "'DUPLICATE_CATALOG_INTERNAL_CODE', 'SOURCE_EVIDENCE_MISSING', "
            "'SOURCE_ACCESS_BLOCKED')",
            name="ck_catalog_kemp_link_resolution_status",
        ),
        CheckConstraint(
            "char_length(input_sha256) = 64 AND char_length(evidence_sha256) = 64",
            name="ck_catalog_kemp_link_resolution_hashes",
        ),
        UniqueConstraint(
            "workspace_id",
            "catalog_item_id",
            "input_sha256",
            name="uq_catalog_kemp_link_resolution_input",
        ),
        Index(
            "ix_catalog_kemp_resolution_batch_item_time",
            "import_batch_id",
            "catalog_item_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    import_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_import_batches.id", ondelete="CASCADE"), index=True
    )
    catalog_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_items.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(48), index=True)
    internal_code_raw: Mapped[str] = mapped_column(Text, default="", server_default="")
    internal_code_norm: Mapped[str] = mapped_column(
        String(255), default="", server_default=""
    )
    method: Mapped[str] = mapped_column(String(80))
    method_version: Mapped[str] = mapped_column(String(80))
    input_sha256: Mapped[str] = mapped_column(String(64))
    evidence_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    evidence_sha256: Mapped[str] = mapped_column(String(64), index=True)
    listing_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CatalogKempOwnedListingLink(Base):
    """Exact owned-listing member of one immutable KEMP resolution."""

    __tablename__ = "catalog_kemp_owned_listing_links"
    __table_args__ = (
        UniqueConstraint(
            "resolution_id", "listing_id", name="uq_catalog_kemp_link_listing"
        ),
        CheckConstraint(
            "char_length(evidence_sha256) = 64",
            name="ck_catalog_kemp_owned_link_hash",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    resolution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_kemp_link_resolutions.id", ondelete="RESTRICT"), index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    catalog_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_items.id", ondelete="RESTRICT"), index=True
    )
    listing_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("listings.id", ondelete="RESTRICT"), index=True
    )
    store_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("marketplace_stores.id", ondelete="RESTRICT"), index=True
    )
    source_listing_id: Mapped[str] = mapped_column(String(255))
    source_url: Mapped[str] = mapped_column(Text)
    internal_code_raw: Mapped[str] = mapped_column(Text)
    internal_code_norm: Mapped[str] = mapped_column(String(255))
    evidence_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    evidence_sha256: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PriceAssessment(Base):
    """Immutable product-price conclusion built from one pricing execution."""

    __tablename__ = "price_assessments"
    __table_args__ = (
        UniqueConstraint("evaluation_key", name="uq_price_assessment_evaluation_key"),
        CheckConstraint(
            "status IN ('OVERPRICED', 'UNDERPRICED', 'IN_MARKET', "
            "'REVIEW_REQUIRED', 'NO_DATA', 'PROCESSING')",
            name="ck_price_assessment_status",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_price_assessment_confidence",
        ),
        Index("ix_price_assessment_product_time", "product_id", "computed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_products.id", ondelete="CASCADE"), index=True
    )
    recommendation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pricing_recommendations.id", ondelete="SET NULL"), index=True
    )
    evaluation_key: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(24))
    our_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    market_low: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    market_high: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    suggested_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    difference_percent: Mapped[Decimal | None] = mapped_column(Numeric(20, 10))
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), default=Decimal("0"), server_default="0"
    )
    evidence_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    reason_codes: Mapped[list[str]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    market_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AttentionItem(TimestampMixin, Base):
    """Mutable pointer to the latest assessment for the daily attention queue."""

    __tablename__ = "attention_items"
    __table_args__ = (
        UniqueConstraint("product_id", name="uq_attention_item_product"),
        CheckConstraint(
            "status IN ('OVERPRICED', 'UNDERPRICED', 'IN_MARKET', "
            "'REVIEW_REQUIRED', 'NO_DATA', 'PROCESSING')",
            name="ck_attention_item_status",
        ),
        CheckConstraint(
            "review_state IN ('OPEN', 'RESOLVED', 'IGNORED')",
            name="ck_attention_item_review_state",
        ),
        Index("ix_attention_workspace_status", "workspace_id", "status", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_products.id", ondelete="CASCADE"), index=True
    )
    latest_assessment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("price_assessments.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(24), default="PROCESSING", server_default="PROCESSING"
    )
    severity: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    review_state: Mapped[str] = mapped_column(
        String(16), default="OPEN", server_default="OPEN"
    )


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


PRICING_RUN_ACTIVE_STATUS_SQL = (
    "'queued', 'running', 'collecting', 'classifying', 'calibrating', "
    "'calculating', 'awaiting_review'"
)


class PricingRun(TimestampMixin, Base):
    __tablename__ = "pricing_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'collecting', 'classifying', 'calibrating', "
            "'calculating', 'awaiting_review', 'completed', 'partial', "
            "'failed', 'cancelled')",
            name="ck_pricing_run_status",
        ),
        CheckConstraint(
            "scope_mode IN ('FULL_CATALOG', 'EXPLICIT_ITEMS')",
            name="ck_pricing_run_scope_mode",
        ),
        CheckConstraint(
            "scope_confirmation_source IN "
            "('OPERATOR', 'AUTOMATED_MONITORING', 'SYSTEM_REPLAY', "
            "'E2E_FIXTURE_REPLAY', 'LEGACY_UNBOUNDED')",
            name="ck_pricing_run_scope_confirmation_source",
        ),
        # Полный каталог, запущенный оператором, обязан нести явное подтверждение.
        # Системные и унаследованные прогоны отмечены другим источником и не
        # притворяются подтверждёнными.
        CheckConstraint(
            "scope_confirmation_source <> 'OPERATOR' "
            "OR scope_mode <> 'FULL_CATALOG' "
            "OR full_catalog_confirmed",
            name="ck_pricing_run_full_catalog_confirmation",
        ),
        # Строка, объявившая версию контракта области, обязана нести и её отпечатки.
        CheckConstraint(
            "scope_contract_version IS NULL OR ("
            "scope_hash IS NOT NULL AND catalog_snapshot_hash IS NOT NULL "
            "AND scope_frozen_at IS NOT NULL)",
            name="ck_pricing_run_scope_manifest_complete",
        ),
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_pricing_run_workspace_idempotency",
        ),
        # --- личность старта (миграция 0038) ---------------------------------
        # NULL означает строку, созданную до этого контракта: у неё нет ни
        # отпечатка запроса, ни актора, и притворяться иначе она не может.
        CheckConstraint(
            "canonical_start_request_hash IS NULL "
            "OR char_length(canonical_start_request_hash) = 64",
            name="ck_pricing_run_start_request_hash",
        ),
        CheckConstraint(
            "start_lane IS NULL OR start_lane IN ('OPERATOR', 'TRUSTED')",
            name="ck_pricing_run_start_lane",
        ),
        # Полоса названа — значит названы и актор, и отпечаток запроса: половина
        # личности не является личностью и сравнивать её нельзя.
        CheckConstraint(
            "start_lane IS NULL OR ("
            "canonical_start_request_hash IS NOT NULL "
            "AND start_actor_id IS NOT NULL "
            "AND start_actor_type IS NOT NULL)",
            name="ck_pricing_run_start_identity_complete",
        ),
        Index("ix_pricing_run_workspace_status", "workspace_id", "status"),
        # Единственная настоящая защита от двух одновременных прогонов по одному
        # импорту: частичный уникальный индекс. SELECT перед вставкой — только
        # быстрый путь, он не выдерживает гонки.
        Index(
            "uq_pricing_run_active_import_batch",
            "workspace_id",
            "import_batch_id",
            unique=True,
            postgresql_where=text(f"status IN ({PRICING_RUN_ACTIVE_STATUS_SQL})"),
        ),
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
    # Полный канонический снимок политики исполнения, а не ярлык версии:
    # исторический вход расчёта, который переживает правку файла развёртывания.
    policy_config: Mapped[dict[str, Any]] = mapped_column(JSON)
    # Отпечаток тех же канонических байт. NULL — прогон до контракта заморозки
    # политики; такие досчитываются по прежнему пути и новым не притворяются.
    policy_snapshot_hash: Mapped[str | None] = mapped_column(String(64))
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

    # --- неизменяемая область прогона ---------------------------------------
    # NULL означает строку, созданную до контракта ограниченного прогона: у неё
    # не было ни манифеста, ни подтверждения, и притворяться иначе нельзя.
    scope_contract_version: Mapped[str | None] = mapped_column(String(40))
    scope_mode: Mapped[str] = mapped_column(
        String(20), default="FULL_CATALOG", server_default="FULL_CATALOG"
    )
    scope_confirmation_source: Mapped[str] = mapped_column(
        String(24), default="LEGACY_UNBOUNDED", server_default="LEGACY_UNBOUNDED"
    )
    full_catalog_confirmed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    catalog_snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    scope_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    scope_manifest: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(160))
    scope_frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- неизменяемая личность старта ----------------------------------------
    # Ключ идемпотентности сам по себе личностью не является: он лишь имя
    # попытки.  Чтобы отличить повтор ТОЙ ЖЕ попытки от чужого запроса под тем
    # же именем, строка обязана помнить, ЧТО именно просили (отпечаток
    # канонического тела старта), КТО просил и ПО КАКОЙ полосе власти.  Без
    # этих трёх колонок «идемпотентный победитель» опознавался по совпадению
    # области, то есть второй актор со своим законным контрактом предпросмотра
    # получал чужой прогон как свой.
    canonical_start_request_hash: Mapped[str | None] = mapped_column(String(64))
    start_lane: Mapped[str | None] = mapped_column(String(24))
    start_actor_id: Mapped[str | None] = mapped_column(String(160))
    start_actor_type: Mapped[str | None] = mapped_column(String(24))
    review_snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    review_frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
            "status IN ('queued', 'discovering', 'awaiting_discovery_review', "
            "'review_frozen', 'collecting', 'collected', 'classified', "
            "'calculating', 'calculated', 'manual_review', 'failed', 'cancelled')",
            name="ck_pricing_run_item_status",
        ),
        Index("ix_pricing_run_item_run_status", "pricing_run_id", "status"),
        # Заморозка состава (миграция 0035): позиция в замороженном списке и
        # сама позиция каталога уникальны в пределах прогона. Объявлены здесь,
        # иначе ``alembic check`` вечно предлагает их удалить.
        Index(
            "uq_pricing_run_item_membership_position",
            "pricing_run_id",
            "membership_position",
            unique=True,
        ),
        Index(
            "uq_pricing_run_item_membership_catalog_item",
            "pricing_run_id",
            "catalog_item_id",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    pricing_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pricing_runs.id", ondelete="CASCADE"), index=True
    )
    # RESTRICT, а не CASCADE: членство прогона — это улика расчёта. Удаление
    # позиции каталога не должно уносить её задним числом (миграция 0033).
    catalog_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_items.id", ondelete="RESTRICT"), index=True
    )
    scrape_target_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("scrape_targets.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(
        String(32), default="queued", server_default="queued"
    )
    idempotency_key: Mapped[str] = mapped_column(String(160))
    task_id: Mapped[str | None] = mapped_column(String(255), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    checkpoint: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- входы на момент старта прогона (детерминированный повтор) ------------
    # Расчёт обязан читать именно эти строки, а не «самую свежую» правку: иначе
    # правка оператора во время сбора попадает в уже начатый прогон.
    # Внешние ключи без ON DELETE намеренно: NO ACTION проверяется в конце
    # оператора, поэтому каскадное удаление рабочей области проходит, а
    # одиночное удаление ссылочной строки — нет.
    catalog_item_override_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog_item_overrides.id"), index=True
    )
    cost_record_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog_item_cost_records.id"), index=True
    )
    start_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
    # Отпечаток замороженного снимка. Расчёт пересчитывает его и отказывается
    # считать при расхождении: снимок, который никто не проверяет, — это не
    # заморозка, а ещё одна изменяемая копия каталога.
    start_snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    # Позиция в замороженном упорядоченном членстве. Порядок — часть контракта
    # (его отпечаток лежит в манифесте), и выводить его из живого каталога
    # нельзя: каталог меняется, а членство прогона — нет.
    membership_position: Mapped[int | None] = mapped_column(Integer)
    no_oe_discovery_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("catalog_discovery_runs.id", ondelete="RESTRICT"), index=True
    )


class PricingDiscoveryReview(Base):
    """Immutable validated Luna assessment for one discovery offer."""

    __tablename__ = "pricing_discovery_reviews"
    __table_args__ = (
        UniqueConstraint(
            "pricing_run_item_id",
            "catalog_discovery_offer_id",
            name="uq_pricing_discovery_review_item_offer",
        ),
        CheckConstraint(
            "verdict IN ('MATCH', 'NO_MATCH', 'INSUFFICIENT_EVIDENCE')",
            name="ck_pricing_discovery_review_verdict",
        ),
        CheckConstraint(
            "char_length(offer_sha256) = 64 AND char_length(prompt_sha256) = 64 "
            "AND char_length(schema_sha256) = 64 AND char_length(model_sha256) = 64 "
            "AND char_length(input_sha256) = 64 AND char_length(output_sha256) = 64",
            name="ck_pricing_discovery_review_hashes",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    pricing_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pricing_runs.id", ondelete="RESTRICT"), index=True
    )
    pricing_run_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pricing_run_items.id", ondelete="RESTRICT"), index=True
    )
    catalog_discovery_offer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_discovery_offers.id", ondelete="RESTRICT"), index=True
    )
    verdict: Mapped[str] = mapped_column(String(32))
    rationale: Mapped[str] = mapped_column(Text)
    evidence_references: Mapped[list[Any]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    conflicts: Mapped[list[Any]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    offer_sha256: Mapped[str] = mapped_column(String(64))
    prompt_sha256: Mapped[str] = mapped_column(String(64))
    schema_sha256: Mapped[str] = mapped_column(String(64))
    model_sha256: Mapped[str] = mapped_column(String(64))
    input_sha256: Mapped[str] = mapped_column(String(64))
    output_sha256: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(160))
    reasoning_effort: Mapped[str] = mapped_column(String(16))
    canonical_input: Mapped[dict[str, Any]] = mapped_column(JSON)
    canonical_output: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PricingDiscoveryDecision(Base):
    """Append-only human admission for one exact offer in one run item."""

    __tablename__ = "pricing_discovery_decisions"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_pricing_discovery_decision_idempotency",
        ),
        Index(
            "ix_pricing_discovery_decision_item_offer_time",
            "pricing_run_item_id",
            "catalog_discovery_offer_id",
            "created_at",
        ),
        CheckConstraint(
            "decision IN ('APPROVE', 'REJECT')",
            name="ck_pricing_discovery_decision_value",
        ),
        CheckConstraint(
            "price > 0 AND char_length(offer_sha256) = 64",
            name="ck_pricing_discovery_decision_snapshot",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    pricing_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pricing_runs.id", ondelete="RESTRICT"), index=True
    )
    pricing_run_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pricing_run_items.id", ondelete="RESTRICT"), index=True
    )
    catalog_discovery_offer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_discovery_offers.id", ondelete="RESTRICT"), index=True
    )
    luna_review_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pricing_discovery_reviews.id", ondelete="RESTRICT"), index=True
    )
    decision: Mapped[str] = mapped_column(String(16))
    actor_id: Mapped[str] = mapped_column(String(160))
    actor_type: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(160))
    offer_sha256: Mapped[str] = mapped_column(String(64))
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3))
    measure_unit: Mapped[str | None] = mapped_column(String(80))
    is_available: Mapped[bool | None] = mapped_column(Boolean)
    seller_id: Mapped[str] = mapped_column(String(255))
    offer_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PricingRunPreviewContract(Base):
    """Выданный сервером контракт предпросмотра — основание старта оператора.

    Токен операторy выдаётся один раз и в базе не хранится: хранится только его
    sha256.  Чтение базы не даёт пригодного к предъявлению токена, а подобрать
    32 случайных байта нельзя.  Строка несёт срок годности, рабочее
    пространство, действующего актора с его ролью и правами, импорт, хеш
    канонического запроса, хеш области, хеш снимка каталога и хеш снимка
    политики: старт обязан совпасть с КАЖДЫМ из них, иначе это другой запрос.
    """

    __tablename__ = "pricing_run_preview_contracts"
    __table_args__ = (
        UniqueConstraint("token_sha256", name="uq_pricing_run_preview_token"),
        CheckConstraint(
            "char_length(token_sha256) = 64 AND char_length(request_hash) = 64 "
            "AND char_length(scope_hash) = 64 "
            "AND char_length(catalog_snapshot_hash) = 64 "
            "AND char_length(policy_snapshot_hash) = 64",
            name="ck_pricing_run_preview_digests",
        ),
        CheckConstraint(
            "expires_at > issued_at",
            name="ck_pricing_run_preview_expiry_after_issue",
        ),
        CheckConstraint(
            "(consumed_at IS NULL AND consumed_idempotency_key IS NULL) OR "
            "(consumed_at IS NOT NULL AND consumed_idempotency_key IS NOT NULL)",
            name="ck_pricing_run_preview_consumption",
        ),
        Index(
            "ix_pricing_run_preview_workspace_batch",
            "workspace_id",
            "import_batch_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    contract_version: Mapped[str] = mapped_column(String(64))
    token_sha256: Mapped[str] = mapped_column(String(64))
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    import_batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_import_batches.id", ondelete="CASCADE"), index=True
    )
    # Актор, роль и права на момент выдачи. Старт под другим актором, другой
    # ролью или с изменившимся набором прав — это другой запрос, а не повтор.
    actor_id: Mapped[str] = mapped_column(String(160))
    actor_type: Mapped[str] = mapped_column(String(24))
    workspace_role: Mapped[str] = mapped_column(String(32))
    permissions: Mapped[list[str]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    scope_mode: Mapped[str] = mapped_column(String(20))
    request_hash: Mapped[str] = mapped_column(String(64))
    scope_hash: Mapped[str] = mapped_column(String(64))
    catalog_snapshot_hash: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(String(80))
    policy_snapshot_hash: Mapped[str] = mapped_column(String(64))
    requires_full_catalog_confirmation: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_idempotency_key: Mapped[str | None] = mapped_column(String(160))
    consumed_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


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
            "(sale_price IS NULL OR sale_price > 0) AND "
            "(reference_price IS NULL OR reference_price > 0)",
            name="ck_market_observation_price_boundaries",
        ),
        CheckConstraint(
            "reference_price IS NULL OR sale_price IS NULL OR "
            "sale_price <= reference_price",
            name="ck_market_observation_sale_not_above_reference",
        ),
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
        CheckConstraint(
            "source_assertion_confidence IS NULL OR "
            "(source_assertion_confidence >= 0 AND source_assertion_confidence <= 1)",
            name="ck_market_observation_source_assertion_confidence",
        ),
        CheckConstraint(
            "source_assertion_retrieval_kind IS NULL OR "
            "source_assertion_capture_sha256 IS NOT NULL",
            name="ck_market_observation_source_assertion_provenance",
        ),
        CheckConstraint(
            "source_assertion_retrieval_kind IS NULL OR "
            "(source_assertion_source IS NOT NULL "
            "AND source_assertion_method IS NOT NULL "
            "AND source_assertion_queried_oe_norm IS NOT NULL)",
            name="ck_market_observation_source_assertion_lineage",
        ),
        CheckConstraint(
            "source_assertion_source IS NULL OR "
            "source_assertion_source = 'PROM_OE_PAGE'",
            name="ck_market_observation_source_assertion_source",
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
    # Normalized, privacy-bounded parser data used by the semantic
    # comparability reviewer.  It deliberately excludes our procurement cost
    # and credentials while retaining every candidate field the parser
    # actually exposed (characteristics and image URLs included).
    candidate_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default="{}"
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
    # ``price`` remains the backwards-compatible active-price field.  The two
    # explicit fields prevent a crossed-out reference price from entering the
    # market cohort as the current sale price.
    sale_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    reference_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
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
        String(80), default="comparison-evidence-v3", server_default="legacy-unknown-v0"
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
    # Утверждение источника об идентичности, первым классом.
    #
    # Признак расширения раньше ехал только внутри ``comparison_evidence``, а
    # кодек этого JSON молча выбрасывает незнакомые ключи при повторном
    # обогащении: номер, по которому взят рынок, терялся. Здесь он хранится
    # рядом с происхождением, на которое опирается, — иначе заявление нечем
    # перепроверить после того, как оно однажды принято.
    via_oe_number: Mapped[str | None] = mapped_column(String(255), index=True)
    source_assertion_retrieval_kind: Mapped[str | None] = mapped_column(String(48))
    #: SHA-256 неизменяемого захвата, на который опирается заявление.
    source_assertion_capture_sha256: Mapped[str | None] = mapped_column(String(64))
    source_assertion_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    #: Родословная приобретения (миграция 0040). Заявление строится только из
    #: неё: запрос никогда не берётся из ``CatalogItem.oe_norm``, иначе
    #: «подтверждением» служит наш же собственный номер.
    source_assertion_source: Mapped[str | None] = mapped_column(String(32))
    source_assertion_method: Mapped[str | None] = mapped_column(String(48))
    source_assertion_queried_oe_norm: Mapped[str | None] = mapped_column(String(255))
    source_assertion_source_url: Mapped[str | None] = mapped_column(String(2048))
    source_assertion_input_hash: Mapped[str | None] = mapped_column(String(64))
    via_cross: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", index=True
    )
    cross_link_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cross_links.id", ondelete="RESTRICT"), index=True
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CandidateComparabilityReview(Base):
    """Immutable semantic review of one market candidate against our product."""

    __tablename__ = "candidate_comparability_reviews"
    __table_args__ = (
        UniqueConstraint(
            "request_key",
            name="uq_candidate_comparability_review_request_key",
        ),
        CheckConstraint(
            "status IN ('COMPLETED', 'HARD_STOP', 'CACHED', 'FAILED', 'SKIPPED')",
            name="ck_candidate_comparability_review_status",
        ),
        CheckConstraint(
            "verdict IN ('COMPARABLE', 'NOT_COMPARABLE', 'INSUFFICIENT_DATA')",
            name="ck_candidate_comparability_review_verdict",
        ),
        CheckConstraint(
            "match_level IN "
            "('EXACT', 'ACCEPTABLE_ANALOGUE', 'SUSPICIOUS', 'NOT_APPLICABLE')",
            name="ck_candidate_comparability_review_match_level",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_candidate_comparability_review_confidence",
        ),
        CheckConstraint(
            "(verdict = 'COMPARABLE' AND "
            "match_level IN ('EXACT', 'ACCEPTABLE_ANALOGUE')) OR "
            "(verdict <> 'COMPARABLE' AND "
            "match_level IN ('SUSPICIOUS', 'NOT_APPLICABLE'))",
            name="ck_candidate_comparability_review_positive_level",
        ),
        CheckConstraint(
            "decision_source IN "
            "('LLM', 'HARD_RULE', 'CACHE', 'HUMAN_CACHE', 'UNCONFIGURED')",
            name="ck_candidate_comparability_review_source",
        ),
        CheckConstraint(
            "(decision_source IN ('CACHE', 'HUMAN_CACHE') AND "
            "cache_hit_review_id IS NOT NULL) OR "
            "(decision_source NOT IN ('CACHE', 'HUMAN_CACHE') AND "
            "cache_hit_review_id IS NULL)",
            name="ck_candidate_comparability_review_cache_source",
        ),
        CheckConstraint(
            "status NOT IN ('FAILED', 'SKIPPED') OR verdict = 'INSUFFICIENT_DATA'",
            name="ck_candidate_comparability_review_failure_verdict",
        ),
        CheckConstraint(
            "attempt_no > 0",
            name="ck_candidate_comparability_review_attempt",
        ),
        CheckConstraint(
            "latency_ms >= 0",
            name="ck_candidate_comparability_review_latency",
        ),
        CheckConstraint(
            "contract_version IN ('comparability-v1', 'comparability-v2')",
            name="ck_candidate_comparability_review_contract",
        ),
        CheckConstraint(
            "contract_version <> 'comparability-v2' OR ("
            "identity_verdict IN ('MATCH', 'NOT_MATCH', 'MANUAL_REVIEW') AND "
            "identity_match_level IN "
            "('EXACT', 'ACCEPTABLE_ANALOGUE', 'SUSPICIOUS', 'NOT_APPLICABLE') AND "
            "identity_match_score >= 0 AND identity_match_score <= 1 AND "
            "decision_confidence >= 0 AND decision_confidence <= 1 AND "
            "image_consistency IN "
            "('SUPPORTS', 'CONFLICTS', 'NON_DIAGNOSTIC', 'UNAVAILABLE') AND "
            "pricing_admission IN ('ADMITTED', 'EXCLUDED', 'MANUAL_REVIEW') AND "
            "reasoning_effort IN ('none', 'low', 'medium', 'high', 'xhigh', 'max') AND "
            "char_length(model_settings_hash) = 64)",
            name="ck_candidate_comparability_review_v2_complete",
        ),
        CheckConstraint(
            "contract_version <> 'comparability-v2' OR "
            "((identity_verdict = 'MATCH' AND identity_match_level IN "
            "('EXACT', 'ACCEPTABLE_ANALOGUE')) OR "
            "(identity_verdict <> 'MATCH' AND identity_match_level IN "
            "('SUSPICIOUS', 'NOT_APPLICABLE')))",
            name="ck_candidate_comparability_review_v2_identity_level",
        ),
        CheckConstraint(
            "contract_version <> 'comparability-v2' OR "
            "((pricing_admission = 'ADMITTED' AND verdict = 'COMPARABLE') OR "
            "(pricing_admission = 'EXCLUDED' AND verdict = 'NOT_COMPARABLE') OR "
            "(pricing_admission = 'MANUAL_REVIEW' AND verdict = 'INSUFFICIENT_DATA'))",
            name="ck_candidate_comparability_review_v2_projection",
        ),
        Index(
            "ix_candidate_comparability_review_observation_time",
            "market_observation_id",
            "reviewed_at",
        ),
        Index(
            "ix_candidate_comparability_review_cache",
            "workspace_id",
            "input_hash",
            "prompt_version",
            "model_id",
        ),
        Index(
            "ix_candidate_comparability_review_model_settings",
            "workspace_id",
            "input_hash",
            "model_settings_hash",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), index=True
    )
    market_observation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("market_observations.id", ondelete="RESTRICT"), index=True
    )
    catalog_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_items.id", ondelete="RESTRICT"), index=True
    )
    request_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    attempt_no: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    prompt_version: Mapped[str] = mapped_column(String(80))
    schema_version: Mapped[str] = mapped_column(String(80))
    contract_version: Mapped[str] = mapped_column(
        String(40), default="comparability-v1", server_default="comparability-v1"
    )
    provider: Mapped[str] = mapped_column(String(50))
    model_id: Mapped[str] = mapped_column(String(160))
    reasoning_effort: Mapped[str | None] = mapped_column(String(16))
    model_settings_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    decision_source: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(20))
    verdict: Mapped[str] = mapped_column(String(24), index=True)
    match_level: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    identity_verdict: Mapped[str | None] = mapped_column(String(24), index=True)
    identity_match_level: Mapped[str | None] = mapped_column(String(32))
    identity_match_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    decision_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    image_consistency: Mapped[str | None] = mapped_column(String(24))
    reason_codes: Mapped[list[str]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    pricing_admission: Mapped[str | None] = mapped_column(String(24), index=True)
    pricing_reason_codes: Mapped[list[str]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    rationale: Mapped[str] = mapped_column(Text)
    dimension_findings: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    hard_stop_conflicts: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    image_urls: Mapped[list[str]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    cache_hit_review_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("candidate_comparability_reviews.id", ondelete="RESTRICT"),
        index=True,
    )
    provider_response_id: Mapped[str | None] = mapped_column(String(255))
    provider_model: Mapped[str | None] = mapped_column(String(160))
    usage: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    estimated_cost: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
    rate_card_version: Mapped[str | None] = mapped_column(String(120))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_detail: Mapped[str | None] = mapped_column(Text)
    # The provider answer that a validator rejected.  A FAILED row otherwise
    # stores a synthesized placeholder, so the citation we paid for and threw
    # away could not be inspected afterwards -- only a truncated error_detail
    # survived, which is not enough to tell a prompt defect from a model one.
    # Safe to keep: the input was already price- and KEMP-redacted, so an answer
    # grounded in it cannot echo what it never saw.
    rejected_output: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CandidateComparabilityFeedback(Base):
    """Append-only customer correction that becomes labelled matching data."""

    __tablename__ = "candidate_comparability_feedback"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('CONFIRM', 'CORRECT')",
            name="ck_candidate_comparability_feedback_decision",
        ),
        CheckConstraint(
            "corrected_verdict IS NULL OR corrected_verdict IN "
            "('COMPARABLE', 'NOT_COMPARABLE', 'INSUFFICIENT_DATA')",
            name="ck_candidate_comparability_feedback_verdict",
        ),
        CheckConstraint(
            "corrected_match_level IS NULL OR corrected_match_level IN "
            "('EXACT', 'ACCEPTABLE_ANALOGUE', 'SUSPICIOUS', 'NOT_APPLICABLE')",
            name="ck_candidate_comparability_feedback_level",
        ),
        CheckConstraint(
            "(decision = 'CONFIRM' AND corrected_verdict IS NULL AND "
            "corrected_match_level IS NULL) OR "
            "(decision = 'CORRECT' AND corrected_verdict IS NOT NULL AND "
            "corrected_match_level IS NOT NULL)",
            name="ck_candidate_comparability_feedback_correction",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_candidate_comparability_feedback_confidence",
        ),
        CheckConstraint(
            "corrected_identity_verdict IS NULL OR corrected_identity_verdict IN "
            "('MATCH', 'NOT_MATCH', 'MANUAL_REVIEW')",
            name="ck_candidate_comparability_feedback_identity_verdict",
        ),
        CheckConstraint(
            "corrected_identity_match_level IS NULL OR corrected_identity_match_level IN "
            "('EXACT', 'ACCEPTABLE_ANALOGUE', 'SUSPICIOUS', 'NOT_APPLICABLE')",
            name="ck_candidate_comparability_feedback_identity_level",
        ),
        CheckConstraint(
            "corrected_pricing_admission IS NULL OR corrected_pricing_admission IN "
            "('ADMITTED', 'EXCLUDED', 'MANUAL_REVIEW')",
            name="ck_candidate_comparability_feedback_pricing_admission",
        ),
        CheckConstraint(
            "(corrected_identity_verdict IS NULL AND "
            "corrected_identity_match_level IS NULL AND "
            "corrected_pricing_admission IS NULL) OR "
            "(decision = 'CORRECT' AND corrected_identity_verdict IS NOT NULL AND "
            "corrected_identity_match_level IS NOT NULL AND "
            "corrected_pricing_admission IS NOT NULL)",
            name="ck_candidate_comparability_feedback_v2_correction",
        ),
        Index(
            "ix_candidate_comparability_feedback_review_time",
            "review_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), index=True
    )
    review_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidate_comparability_reviews.id", ondelete="RESTRICT"),
        index=True,
    )
    market_observation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("market_observations.id", ondelete="RESTRICT"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    decision: Mapped[str] = mapped_column(String(16))
    corrected_verdict: Mapped[str | None] = mapped_column(String(24))
    corrected_match_level: Mapped[str | None] = mapped_column(String(32))
    corrected_identity_verdict: Mapped[str | None] = mapped_column(String(24))
    corrected_identity_match_level: Mapped[str | None] = mapped_column(String(32))
    corrected_pricing_admission: Mapped[str | None] = mapped_column(String(24))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    reason: Mapped[str] = mapped_column(Text)
    evidence_corrections: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


#: Statuses an extraction row may carry.  ``UNCONFIGURED`` is the typed outcome
#: of "the feature is switched on but no credential is present": it is a row, so
#: an operator sees the gap, and the check constraints below make it impossible
#: for such a row to claim a provider response.
AI_EVIDENCE_EXTRACTION_STATUSES = (
    "COMPLETED",
    "CACHED",
    "FAILED",
    "SKIPPED",
    "UNCONFIGURED",
)

#: Statuses that never involve an HTTP request.  A row in one of these states
#: carrying a provider response id would mean the request happened after all,
#: which is exactly the failure the ``off``/missing-key contract forbids.
AI_EVIDENCE_NO_REQUEST_STATUSES = ("SKIPPED", "UNCONFIGURED")

AI_EVIDENCE_VERIFICATION_STATUSES = (
    "VERIFIED",
    "PARTIALLY_VERIFIED",
    "REJECTED",
    "NOT_RUN",
)


class AiEvidenceRequestEvent(Base):
    """Immutable pre-transmission record for one logical provider request."""

    __tablename__ = "ai_evidence_request_events"
    __table_args__ = (
        UniqueConstraint("request_key", name="uq_ai_evidence_request_event_key"),
        UniqueConstraint(
            "workspace_id",
            "market_observation_id",
            "input_hash",
            "attempt_no",
            name="uq_ai_evidence_request_event_attempt",
        ),
        CheckConstraint("attempt_no > 0", name="ck_ai_evidence_request_attempt"),
        CheckConstraint(
            "char_length(request_key) = 64 AND char_length(input_hash) = 64 AND "
            "char_length(prepared_input_sha256) = 64 AND "
            "char_length(capture_sha256) = 64 AND "
            "char_length(candidate_snapshot_sha256) = 64 AND "
            "char_length(source_offer_locator_sha256) = 64 AND "
            "char_length(document_sha256) = 64 AND "
            "char_length(model_settings_sha256) = 64",
            name="ck_ai_evidence_request_digest_shape",
        ),
        CheckConstraint(
            "max_output_tokens > 0 AND max_input_chars > 0",
            name="ck_ai_evidence_request_bounds",
        ),
        Index(
            "ix_ai_evidence_request_input",
            "workspace_id",
            "market_observation_id",
            "input_hash",
            "attempt_no",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), index=True
    )
    pricing_run_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pricing_run_items.id", ondelete="RESTRICT"), index=True
    )
    market_observation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("market_observations.id", ondelete="RESTRICT"), index=True
    )
    raw_capture_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("raw_market_captures.id", ondelete="RESTRICT"), index=True
    )
    request_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    attempt_no: Mapped[int] = mapped_column(Integer)
    source_listing_id: Mapped[str] = mapped_column(String(255))
    capture_sha256: Mapped[str] = mapped_column(String(64))
    candidate_snapshot_sha256: Mapped[str] = mapped_column(String(64))
    source_offer_locator_sha256: Mapped[str] = mapped_column(String(64))
    document_sha256: Mapped[str] = mapped_column(String(64))
    prepared_input_sha256: Mapped[str] = mapped_column(String(64))
    model_settings_sha256: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(80))
    schema_version: Mapped[str] = mapped_column(String(80))
    extractor_version: Mapped[str] = mapped_column(String(80))
    verifier_version: Mapped[str] = mapped_column(String(80))
    oe_normalization_version: Mapped[str] = mapped_column(String(80))
    provider: Mapped[str] = mapped_column(String(50))
    model_id: Mapped[str] = mapped_column(String(160))
    reasoning_effort: Mapped[str] = mapped_column(String(16))
    max_output_tokens: Mapped[int] = mapped_column(Integer)
    max_input_chars: Mapped[int] = mapped_column(Integer)
    target_fields: Mapped[list[str]] = mapped_column(JSON)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AiEvidenceRequestClaim(Base):
    """Append-only lease claim for sending or recovering one request event."""

    __tablename__ = "ai_evidence_request_claims"
    __table_args__ = (
        UniqueConstraint("claim_token", name="uq_ai_evidence_request_claim_token"),
        Index(
            "ix_ai_evidence_request_claim_latest",
            "request_event_id",
            "claimed_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    request_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_evidence_request_events.id", ondelete="RESTRICT"), index=True
    )
    claim_token: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True, index=True)
    recovery: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    claimed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    lease_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class AiEvidenceExtraction(Base):
    """Append-only record of one AI-assisted evidence extraction attempt.

    Deliberately a separate table from ``candidate_comparability_reviews`` and
    not a widening of it.  The two answer different questions -- "is this offer
    the same product" versus "what does this capture literally say" -- they
    version independently, and a shared table would have made every column of
    each nullable for the other, which is how a check constraint stops being
    able to say anything.

    Identity is built by :meth:`build_input_hash` and :meth:`build_request_key`
    rather than by the caller assembling a dict, because the whole cache
    contract rests on *which* facts are inside the digest.  A capture hash left
    out of it (the classic version of this bug) makes a re-scraped page with new
    prices reuse the answer computed for the old one -- a stale extraction that
    looks like a cache hit and is indistinguishable from a fresh one in the
    record.
    """

    __tablename__ = "ai_evidence_extractions"
    __table_args__ = (
        UniqueConstraint(
            "request_key",
            name="uq_ai_evidence_extraction_request_key",
        ),
        CheckConstraint(
            "status IN ('COMPLETED', 'CACHED', 'FAILED', 'SKIPPED', 'UNCONFIGURED')",
            name="ck_ai_evidence_extraction_status",
        ),
        CheckConstraint(
            "verification_status IN "
            "('VERIFIED', 'PARTIALLY_VERIFIED', 'REJECTED', 'NOT_RUN')",
            name="ck_ai_evidence_extraction_verification_status",
        ),
        # A cache hit must name the row it reused, and a row that is not a cache
        # hit must not pretend to be one.  Without both directions "CACHED" is
        # an unfalsifiable label.
        CheckConstraint(
            "(status = 'CACHED' AND cache_hit_extraction_id IS NOT NULL) OR "
            "(status <> 'CACHED' AND cache_hit_extraction_id IS NULL)",
            name="ck_ai_evidence_extraction_cache_binding",
        ),
        # The persisted half of the "missing key performs no request" contract.
        # A service that regressed into calling the provider anyway could not
        # store the evidence of it under these statuses.
        CheckConstraint(
            "status NOT IN ('SKIPPED', 'UNCONFIGURED') OR "
            "(provider_response_id IS NULL AND provider_model IS NULL AND "
            "raw_output IS NULL AND latency_ms = 0 AND "
            "usage::jsonb = '{}'::jsonb)",
            name="ck_ai_evidence_extraction_no_request_states",
        ),
        CheckConstraint(
            "(status = 'FAILED' AND error_code IS NOT NULL) OR (status <> 'FAILED')",
            name="ck_ai_evidence_extraction_failure_code",
        ),
        CheckConstraint(
            "status <> 'COMPLETED' OR error_code IS NULL",
            name="ck_ai_evidence_extraction_completed_clean",
        ),
        CheckConstraint(
            "char_length(request_key) = 64 AND char_length(input_hash) = 64 AND "
            "char_length(candidate_snapshot_hash) = 64 AND "
            "char_length(capture_sha256) = 64 AND "
            "char_length(source_offer_locator_sha256) = 64 AND "
            "char_length(document_sha256) = 64 AND "
            "char_length(prepared_input_sha256) = 64 AND "
            "char_length(model_settings_sha256) = 64",
            name="ck_ai_evidence_extraction_digest_shape",
        ),
        CheckConstraint("attempt_no > 0", name="ck_ai_evidence_extraction_attempt"),
        CheckConstraint("latency_ms >= 0", name="ck_ai_evidence_extraction_latency"),
        CheckConstraint(
            "reasoning_effort IN ('none', 'low', 'medium', 'high', 'xhigh', 'max')",
            name="ck_ai_evidence_extraction_reasoning_effort",
        ),
        CheckConstraint(
            "mode IN ('off', 'shadow')",
            name="ck_ai_evidence_extraction_mode",
        ),
        CheckConstraint(
            "max_output_tokens > 0 AND max_input_chars > 0",
            name="ck_ai_evidence_extraction_bounds",
        ),
        Index(
            "ix_ai_evidence_extraction_cache",
            "workspace_id",
            "input_hash",
            "status",
        ),
        Index(
            "ix_ai_evidence_extraction_observation_time",
            "market_observation_id",
            "extracted_at",
        ),
        Index(
            "ix_ai_evidence_extraction_position_time",
            "pricing_run_item_id",
            "extracted_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), index=True
    )
    pricing_run_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pricing_run_items.id", ondelete="RESTRICT"), index=True
    )
    market_observation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("market_observations.id", ondelete="RESTRICT"), index=True
    )
    raw_capture_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("raw_market_captures.id", ondelete="RESTRICT"), index=True
    )
    request_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_evidence_request_events.id", ondelete="RESTRICT"),
        unique=True,
        index=True,
    )
    request_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    candidate_snapshot_hash: Mapped[str] = mapped_column(String(64))
    capture_sha256: Mapped[str] = mapped_column(String(64), index=True)
    source_listing_id: Mapped[str] = mapped_column(String(255))
    source_offer_locator_sha256: Mapped[str] = mapped_column(String(64))
    document_sha256: Mapped[str] = mapped_column(String(64))
    prepared_input_sha256: Mapped[str] = mapped_column(String(64))
    model_settings_sha256: Mapped[str] = mapped_column(String(64))
    attempt_no: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    prompt_version: Mapped[str] = mapped_column(String(80))
    schema_version: Mapped[str] = mapped_column(String(80))
    extractor_version: Mapped[str] = mapped_column(String(80))
    provider: Mapped[str] = mapped_column(String(50))
    model_id: Mapped[str] = mapped_column(String(160))
    reasoning_effort: Mapped[str] = mapped_column(String(16))
    max_output_tokens: Mapped[int] = mapped_column(Integer)
    max_input_chars: Mapped[int] = mapped_column(Integer)
    target_fields: Mapped[list[str]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    verifier_version: Mapped[str] = mapped_column(String(80))
    oe_normalization_version: Mapped[str] = mapped_column(String(80))
    mode: Mapped[str] = mapped_column(String(16))
    outcome: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(20), index=True)
    #: The provider's strict-schema payload exactly as parsed, kept whole so a
    #: later schema version can be re-derived without another paid call.
    #:
    #: ``none_as_null`` is load-bearing, not tidiness.  A plain ``JSON`` column
    #: stores Python ``None`` as the JSON scalar ``null``, which is a *value*:
    #: ``raw_output IS NULL`` is then false, and the check constraint asserting
    #: that a no-request row carries no provider payload silently stops holding.
    #: "Absent" and "the provider answered null" must not be the same state.
    raw_output: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))
    #: The typed per-field findings the extractor produced from ``raw_output``.
    findings: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    #: What the *deterministic* verifier concluded about those findings.  The
    #: model's own confidence is not evidence; this column is what downstream
    #: code is allowed to trust.
    verification_status: Mapped[str] = mapped_column(
        String(24), default="NOT_RUN", server_default="NOT_RUN"
    )
    verification_reasons: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
    verification_report: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
    verified_field_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    rejected_field_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
    cache_hit_extraction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_evidence_extractions.id", ondelete="RESTRICT"), index=True
    )
    provider_response_id: Mapped[str | None] = mapped_column(String(255))
    provider_model: Mapped[str | None] = mapped_column(String(160))
    usage: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_detail: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    @staticmethod
    def build_input_hash(
        *,
        capture_sha256: str,
        candidate_snapshot_hash: str,
        prompt_version: str,
        schema_version: str,
        extractor_version: str,
        provider: str,
        model_id: str,
        reasoning_effort: str,
        verifier_version: str,
        oe_normalization_version: str,
    ) -> str:
        """The digest that decides whether two extractions are the same work.

        Every argument is load-bearing and none of them is optional, which is
        the point: an omitted one cannot be spotted at the call site, and the
        symptom -- a reused answer for changed evidence -- surfaces as a cache
        hit rather than as an error.

        ``capture_sha256`` and ``candidate_snapshot_hash`` are the evidence;
        the versions and the model/effort triple are the interpretation of it.
        Changing any one of the eight yields a different identity, so a re-scrape
        or a model/effort/prompt bump is a cache *miss* by construction rather
        than by remembering to invalidate something.
        """

        return _canonical_identity_digest(
            {
                "kind": "ai_evidence_extraction_input",
                "capture_sha256": capture_sha256,
                "candidate_snapshot_hash": candidate_snapshot_hash,
                "prompt_version": prompt_version,
                "schema_version": schema_version,
                "extractor_version": extractor_version,
                "provider": provider,
                "model_id": model_id,
                "reasoning_effort": reasoning_effort,
                "verifier_version": verifier_version,
                "oe_normalization_version": oe_normalization_version,
            }
        )

    @staticmethod
    def build_request_key(
        *,
        market_observation_id: uuid.UUID | str,
        input_hash: str,
        attempt_no: int,
    ) -> str:
        """Idempotency identity for one physical extraction attempt.

        ``input_hash`` already carries the evidence and the interpretation, so
        this adds only what distinguishes two rows that legitimately share it:
        the observation the answer is filed against, and the attempt number.
        The unique index on the column is therefore what makes a concurrent
        double-write of the *same* attempt lose loudly instead of billing twice.
        """

        return _canonical_identity_digest(
            {
                "kind": "ai_evidence_extraction_request",
                "market_observation_id": str(market_observation_id),
                "input_hash": input_hash,
                "attempt_no": int(attempt_no),
            }
        )


def _canonical_identity_digest(payload: dict[str, Any]) -> str:
    """SHA-256 over a canonical JSON encoding of scalar identity facts.

    Local rather than imported from ``services.decision_fingerprint``: a
    persistence model must not depend on the service layer, and the inputs here
    are plain strings and ints, so the general canonicalizer's Decimal/datetime
    handling would buy nothing.
    """

    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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


class CatalogIdentityLink(Base):
    """Append-only equivalence edge between two numbers of our own catalog item.

    Deliberately a separate table rather than a nullable ``pricing_run_id`` on
    ``cross_links`` (WP-3 chose option B, and the reason is recorded here rather
    than left to archaeology).  A link read out of our own catalogue, the
    reference map or a kemp.ua card belongs to no pricing run at all: it was not
    observed while pricing anything.  Making ``cross_links.pricing_run_id``
    nullable would weaken the append-only invariant of runs — every row there is
    currently guaranteed to name the run that produced it — and would put two
    things with different lifecycles in one table: a run's links die with the
    run's evidence, these outlive every run.

    The two tables are read as a union by ``_confirmed_cross_oems``.  Both sides
    filter on ``validation_status == 'CONFIRMED'``, so a ``REVIEW`` row here can
    never move a price.
    """

    __tablename__ = "catalog_identity_links"
    __table_args__ = (
        # One row per (item, pair, source): the same pair from two sources must
        # both be recordable, because two independent sources agreeing is what
        # promotes a KEMP_SITE link out of REVIEW.  Re-running the reparse with
        # the same inputs therefore collides instead of duplicating.
        UniqueConstraint(
            "catalog_item_id",
            "our_oem_norm",
            "extracted_oem_norm",
            "extraction_method",
            name="uq_catalog_identity_link_pair_source",
        ),
        UniqueConstraint("sequence_no", name="uq_catalog_identity_link_sequence"),
        CheckConstraint(
            "our_oem_norm <> '' AND extracted_oem_norm <> '' "
            "AND our_oem_norm <> extracted_oem_norm",
            name="ck_catalog_identity_link_distinct_oems",
        ),
        # REJECTED is absent on purpose: these sources can be silent about a
        # link, and silence is not disproof.
        CheckConstraint(
            "validation_status IN ('CONFIRMED', 'REVIEW')",
            name="ck_catalog_identity_link_status",
        ),
        CheckConstraint(
            "anomaly IS NULL OR anomaly IN "
            "('OE_SOURCE_CONFLICT', 'SHARED_ARTICLE_FANOUT', "
            "'OE_SUPERSEDED_BY_NEWER_REFERENCE', 'SOURCE_SEMANTIC_CONFLICT', "
            "'PUBLIC_NUMBER_SEMANTIC_FANOUT', 'STALE_AFTER_REPARSE')",
            name="ck_catalog_identity_link_anomaly",
        ),
        # An anomaly means we cannot tell which number is right, so the link
        # must not be usable as evidence until a human says otherwise.
        CheckConstraint(
            "anomaly IS NULL OR validation_status = 'REVIEW'",
            name="ck_catalog_identity_link_anomaly_under_review",
        ),
        Index(
            "ix_catalog_identity_link_workspace_pair",
            "workspace_id",
            "our_oem_norm",
            "extracted_oem_norm",
        ),
        Index(
            "ix_catalog_identity_link_workspace_extracted",
            "workspace_id",
            "extracted_oem_norm",
        ),
        Index(
            "ix_catalog_identity_link_anomaly",
            "workspace_id",
            "anomaly",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    sequence_no: Mapped[int] = mapped_column(BigInteger, Identity(), nullable=False)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="RESTRICT"), index=True
    )
    catalog_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_items.id", ondelete="CASCADE"), index=True
    )
    our_oem_norm: Mapped[str] = mapped_column(String(255))
    extracted_oem_norm: Mapped[str] = mapped_column(String(255))
    #: The number as the source wrote it.  ``6455.EE`` carries its punctuation
    #: as a marque signal that normalization erases.
    extracted_raw: Mapped[str] = mapped_column(Text)
    #: The whole original line the number was read out of — the proof that lets
    #: a human check the decision by eye instead of trusting the pipeline.
    raw_context: Mapped[str] = mapped_column(Text)
    extraction_method: Mapped[str] = mapped_column(String(50))
    validation_status: Mapped[str] = mapped_column(String(16))
    anomaly: Mapped[str | None] = mapped_column(String(40))
    #: Every source that produced this pair, most trusted first.
    corroborating_sources: Mapped[list[str]] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    validation_details: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
    method_version: Mapped[str] = mapped_column(String(80))
    config_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
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


class FitmentSource(Base):
    """Versioned source-policy snapshot; rows are append-only."""

    __tablename__ = "fitment_sources"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "source_key", "policy_version", name="uq_fit_source_policy"
        ),
        CheckConstraint(
            "source_tier IN ('A', 'B', 'C', 'D', 'E')",
            name="ck_fit_source_tier",
        ),
        CheckConstraint(
            "base_reliability >= 0 AND base_reliability <= 1",
            name="ck_fit_source_reliability",
        ),
        CheckConstraint(
            "(source_tier = 'A' AND base_reliability BETWEEN 0.95 AND 1.00) OR "
            "(source_tier = 'B' AND base_reliability BETWEEN 0.75 AND 0.90) OR "
            "(source_tier = 'C' AND base_reliability BETWEEN 0.55 AND 0.75) OR "
            "(source_tier = 'D' AND base_reliability BETWEEN 0.30 AND 0.55) OR "
            "(source_tier = 'E' AND base_reliability BETWEEN 0.10 AND 0.35)",
            name="ck_fit_source_tier_reliability",
        ),
        CheckConstraint(
            "access_status IN ('PERMITTED', 'OWNER_RISK_ACCEPTED', "
            "'NOT_PERMITTED', 'UNKNOWN')",
            name="ck_fit_source_access",
        ),
        CheckConstraint(
            "access_status NOT IN ('PERMITTED', 'OWNER_RISK_ACCEPTED') OR "
            "(char_length(trim(access_reference)) > 0 AND robots_checked AND terms_checked)",
            name="ck_fit_source_approved_review",
        ),
        Index("ix_fit_source_workspace_key", "workspace_id", "source_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    source_key: Mapped[str] = mapped_column(String(160))
    source_type: Mapped[str] = mapped_column(String(80))
    source_tier: Mapped[str] = mapped_column(String(1))
    base_reliability: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    domain: Mapped[str] = mapped_column(String(255))
    access_method: Mapped[str] = mapped_column(String(80))
    access_status: Mapped[str] = mapped_column(String(24))
    access_reference: Mapped[str] = mapped_column(String(255))
    robots_checked: Mapped[bool] = mapped_column(Boolean)
    terms_checked: Mapped[bool] = mapped_column(Boolean)
    rate_limit: Mapped[str] = mapped_column(String(120))
    cache_policy: Mapped[str] = mapped_column(String(120))
    policy_version: Mapped[str] = mapped_column(String(80))
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FitmentSourceDocument(Base):
    """Immutable query-level retrieval metadata; no bulk catalogue mirror."""

    __tablename__ = "fitment_source_documents"
    __table_args__ = (
        UniqueConstraint(
            "source_id", "content_sha256", name="uq_fit_source_document_hash"
        ),
        CheckConstraint(
            "char_length(content_sha256) = 64", name="ck_fit_source_document_hash"
        ),
        Index("ix_fit_source_document_retrieved", "source_id", "retrieved_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fitment_sources.id", ondelete="RESTRICT"), index=True
    )
    source_url: Mapped[str] = mapped_column(Text)
    retrieval_query: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)
    content_locator: Mapped[str | None] = mapped_column(Text)
    response_metadata: Mapped[dict[str, Any]] = mapped_column(JSON)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SellerRelationRecord(Base):
    """Append-only workspace seller classification with explicit provenance."""

    __tablename__ = "seller_relation_records"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_seller_relation_idempotency"
        ),
        CheckConstraint(
            "relation IN ('own', 'related', 'possibly_related', "
            "'independent', 'unknown')",
            name="ck_seller_relation_value",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_seller_relation_confidence",
        ),
        Index(
            "ix_seller_relation_current",
            "workspace_id",
            "marketplace",
            "seller_external_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    marketplace: Mapped[str] = mapped_column(String(32))
    seller_external_id: Mapped[str] = mapped_column(String(255))
    seller_name: Mapped[str | None] = mapped_column(String(255))
    relation: Mapped[str] = mapped_column(String(24))
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(64))
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("seller_relation_records.id", ondelete="RESTRICT"), index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FitmentAnalysis(TimestampMixin, Base):
    """Idempotent analysis job over one catalog item and evidence snapshot."""

    __tablename__ = "fitment_analyses"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_fit_analysis_idempotency"
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'partial', 'failed')",
            name="ck_fit_analysis_status",
        ),
        CheckConstraint(
            "workflow_state IN ('NEW', 'NORMALIZED', 'TARGET_VERIFICATION_STARTED', "
            "'TARGET_VERIFIED', 'CANDIDATES_DISCOVERED', 'SELLERS_RESOLVED', "
            "'EVIDENCE_COLLECTION_STARTED', 'EVIDENCE_COLLECTED', "
            "'FITMENT_EVALUATED', 'PRICE_COMPARABILITY_EVALUATED', "
            "'MARKET_ANALYZED', 'RECOMMENDATION_READY', 'NOTIFIED', "
            "'UNDER_REVIEW', 'ACCEPTED', 'ACCEPTED_WITH_MODIFICATION', "
            "'REJECTED', 'DEFERRED', 'RESEARCH_REQUESTED', "
            "'PARTIAL_FAILURE', 'FAILED')",
            name="ck_fit_analysis_workflow_state",
        ),
        CheckConstraint(
            "candidate_count >= 0 AND completed_candidate_count >= 0 "
            "AND failed_candidate_count >= 0 AND attempt_count >= 0",
            name="ck_fit_analysis_counts",
        ),
        Index("ix_fit_analysis_product_time", "catalog_item_id", "created_at"),
        Index("ix_fit_analysis_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    catalog_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_items.id", ondelete="CASCADE"), index=True
    )
    pricing_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pricing_runs.id", ondelete="SET NULL"), index=True
    )
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(
        String(16), default="queued", server_default="queued"
    )
    workflow_state: Mapped[str] = mapped_column(
        String(40), default="NEW", server_default="NEW", index=True
    )
    target_identity: Mapped[dict[str, Any]] = mapped_column(JSON)
    target_commercial_context: Mapped[dict[str, Any]] = mapped_column(JSON)
    source_policy_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    contract_version: Mapped[str] = mapped_column(String(80))
    scoring_version: Mapped[str] = mapped_column(String(80))
    request_sha256: Mapped[str] = mapped_column(String(64))
    dispatch_task_id: Mapped[str | None] = mapped_column(String(255), index=True)
    owner_task_id: Mapped[str | None] = mapped_column(String(255), index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    candidate_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    completed_candidate_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    failed_candidate_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    error: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FitmentCandidateAssessment(Base):
    """Immutable scoring result for one persisted market observation."""

    __tablename__ = "fitment_candidate_assessments"
    __table_args__ = (
        UniqueConstraint(
            "analysis_id", "market_observation_id", name="uq_fit_assessment_candidate"
        ),
        CheckConstraint(
            "compatibility_status IN ('confirmed_compatible', 'likely_compatible', "
            "'uncertain', 'not_compatible')",
            name="ck_fit_assessment_status",
        ),
        CheckConstraint(
            "compatibility_probability >= 0 AND compatibility_probability <= 1 "
            "AND positive_evidence >= 0 AND positive_evidence <= 1 "
            "AND negative_evidence >= 0 AND negative_evidence <= 1 "
            "AND coverage >= 0 AND coverage <= 1 "
            "AND contradiction_rate >= 0 AND contradiction_rate <= 1 "
            "AND missing_critical_ratio >= 0 AND missing_critical_ratio <= 1",
            name="ck_fit_assessment_scores",
        ),
        CheckConstraint(
            "price_comparability_status IN ('comparable', 'manual_review', "
            "'not_comparable')",
            name="ck_fit_assessment_price_status",
        ),
        CheckConstraint(
            "competitor_weight >= 0 AND competitor_weight <= 1",
            name="ck_fit_assessment_weight",
        ),
        CheckConstraint(
            "price_unit_status IN ('verified_piece', 'normalized_pair', "
            "'normalized_axle_set', 'normalized_kit', 'unknown', 'incompatible') "
            "AND price_unit_certainty BETWEEN 0 AND 1 "
            "AND (normalized_unit_price IS NULL OR normalized_unit_price > 0)",
            name="ck_fit_assessment_price_unit",
        ),
        CheckConstraint(
            "NOT automatic_price_change_allowed",
            name="ck_fit_assessment_no_auto_price",
        ),
        Index(
            "ix_fit_assessment_analysis_status", "analysis_id", "compatibility_status"
        ),
        Index("ix_fit_assessment_observation", "market_observation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fitment_analyses.id", ondelete="CASCADE"), index=True
    )
    market_observation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("market_observations.id", ondelete="RESTRICT")
    )
    seller_relation_record_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("seller_relation_records.id", ondelete="RESTRICT"), index=True
    )
    candidate_identity: Mapped[dict[str, Any]] = mapped_column(JSON)
    candidate_commercial_context: Mapped[dict[str, Any]] = mapped_column(JSON)
    compatibility_status: Mapped[str] = mapped_column(String(32))
    compatibility_probability: Mapped[Decimal] = mapped_column(Numeric(7, 6))
    positive_evidence: Mapped[Decimal] = mapped_column(Numeric(7, 6))
    negative_evidence: Mapped[Decimal] = mapped_column(Numeric(7, 6))
    coverage: Mapped[Decimal] = mapped_column(Numeric(7, 6))
    contradiction_rate: Mapped[Decimal] = mapped_column(Numeric(7, 6))
    missing_critical_ratio: Mapped[Decimal] = mapped_column(Numeric(7, 6))
    hard_rejections: Mapped[list[str]] = mapped_column(JSON)
    reason_codes: Mapped[list[str]] = mapped_column(JSON)
    missing_critical_fields: Mapped[list[str]] = mapped_column(JSON)
    feature_consensus: Mapped[dict[str, Any]] = mapped_column(JSON)
    authoritative_confirmation: Mapped[bool] = mapped_column(Boolean)
    requires_manual_review: Mapped[bool] = mapped_column(Boolean)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON)
    price_comparability_status: Mapped[str] = mapped_column(String(24))
    price_eligible: Mapped[bool] = mapped_column(Boolean)
    competitor_weight: Mapped[Decimal] = mapped_column(Numeric(9, 8))
    normalized_unit_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    price_unit_status: Mapped[str] = mapped_column(
        String(32), default="unknown", server_default="unknown"
    )
    price_unit_certainty: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), default=Decimal("0.3"), server_default="0.3"
    )
    price_factor_trace: Mapped[dict[str, Any]] = mapped_column(JSON)
    price_reason_codes: Mapped[list[str]] = mapped_column(JSON)
    automatic_price_change_allowed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    contract_version: Mapped[str] = mapped_column(String(80))
    scoring_version: Mapped[str] = mapped_column(String(80))
    assessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FitmentEvidenceClaim(Base):
    """Append-only source claim used by a candidate assessment."""

    __tablename__ = "fitment_evidence_claims"
    __table_args__ = (
        UniqueConstraint(
            "analysis_id", "evidence_key", name="uq_fit_evidence_analysis_key"
        ),
        CheckConstraint(
            "feature IN ('oe_exact', 'oe_supersession', 'cross_confirmed', "
            "'part_category', 'axle', 'side', 'vehicle_make_model', "
            "'generation', 'year_overlap', 'engine', 'body', 'vehicle_market', "
            "'technical_specs')",
            name="ck_fit_evidence_feature",
        ),
        CheckConstraint(
            "evidence_value IN (-1, -0.5, 0, 0.5, 1)",
            name="ck_fit_evidence_value",
        ),
        CheckConstraint(
            "source_tier IN ('A', 'B', 'C', 'D', 'E')",
            name="ck_fit_evidence_source_tier",
        ),
        CheckConstraint(
            "source_reliability BETWEEN 0 AND 1 "
            "AND extraction_confidence BETWEEN 0 AND 1 "
            "AND directness BETWEEN 0 AND 1 "
            "AND independence_factor BETWEEN 0 AND 1 "
            "AND freshness_factor BETWEEN 0 AND 1",
            name="ck_fit_evidence_factors",
        ),
        CheckConstraint(
            "polarity IN ('supports', 'contradicts', 'neutral', 'unknown')",
            name="ck_fit_evidence_polarity",
        ),
        CheckConstraint(
            "statement_status IN ('FACT', 'INFERENCE', 'ASSUMPTION', "
            "'UNKNOWN', 'CONFLICT')",
            name="ck_fit_evidence_statement",
        ),
        Index("ix_fit_evidence_assessment_feature", "assessment_id", "feature"),
        Index("ix_fit_evidence_correlation", "analysis_id", "correlation_group"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fitment_analyses.id", ondelete="CASCADE"), index=True
    )
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fitment_candidate_assessments.id", ondelete="CASCADE"), index=True
    )
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fitment_source_documents.id", ondelete="RESTRICT"), index=True
    )
    evidence_key: Mapped[str] = mapped_column(String(255))
    feature: Mapped[str] = mapped_column(String(40))
    evidence_value: Mapped[Decimal] = mapped_column(Numeric(3, 1))
    source_external_id: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(80))
    source_tier: Mapped[str] = mapped_column(String(1))
    source_reliability: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    extraction_confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    directness: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), default=Decimal("1"), server_default="1"
    )
    independence_factor: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    freshness_factor: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    correlation_group: Mapped[str] = mapped_column(String(255))
    polarity: Mapped[str] = mapped_column(String(16))
    statement_status: Mapped[str] = mapped_column(String(16))
    claim_value: Mapped[dict[str, Any]] = mapped_column(JSON)
    source_url: Mapped[str | None] = mapped_column(Text)
    raw_fragment: Mapped[str | None] = mapped_column(Text)
    source_document_sha256: Mapped[str | None] = mapped_column(String(64))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FitmentHumanReview(Base):
    """Append-only human label for candidate compatibility."""

    __tablename__ = "fitment_human_reviews"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_fit_review_idempotency"
        ),
        CheckConstraint(
            "decision IN ('mark_candidate_compatible', 'mark_candidate_incompatible', "
            "'postpone', 'request_additional_check')",
            name="ck_fit_review_decision",
        ),
        Index("ix_fit_review_assessment_time", "assessment_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fitment_candidate_assessments.id", ondelete="RESTRICT"), index=True
    )
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(40))
    reason_code: Mapped[str] = mapped_column(String(80))
    comment: Mapped[str | None] = mapped_column(Text)
    system_status_snapshot: Mapped[str] = mapped_column(String(32))
    system_probability_snapshot: Mapped[Decimal] = mapped_column(Numeric(7, 6))
    evidence_snapshot_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FitmentCrossReference(Base):
    """Versioned, append-only internal cross-reference knowledge record."""

    __tablename__ = "fitment_cross_references"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "record_fingerprint", name="uq_fit_cross_fingerprint"
        ),
        CheckConstraint(
            "relation_status IN ('machine_discovered', 'source_confirmed', "
            "'human_confirmed', 'human_rejected', 'conflicting', "
            "'deprecated', 'superseded')",
            name="ck_fit_cross_status",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1 AND source_count >= 0 "
            "AND human_feedback_count >= 0",
            name="ck_fit_cross_metrics",
        ),
        Index(
            "ix_fit_cross_lookup",
            "workspace_id",
            "normalized_article",
            "normalized_oe",
            "relation_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    brand: Mapped[str] = mapped_column(String(255))
    normalized_brand: Mapped[str] = mapped_column(String(255), index=True)
    article: Mapped[str] = mapped_column(String(255))
    normalized_article: Mapped[str] = mapped_column(String(255), index=True)
    oe: Mapped[str] = mapped_column(String(255))
    normalized_oe: Mapped[str] = mapped_column(String(255), index=True)
    installation_position: Mapped[str | None] = mapped_column(String(80))
    vehicle_key: Mapped[str | None] = mapped_column(String(255))
    relation_status: Mapped[str] = mapped_column(String(24))
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    evidence_ids: Mapped[list[str]] = mapped_column(JSON)
    source_count: Mapped[int] = mapped_column(Integer)
    human_feedback_count: Mapped[int] = mapped_column(Integer)
    record_fingerprint: Mapped[str] = mapped_column(String(64))
    method_version: Mapped[str] = mapped_column(String(80))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fitment_cross_references.id", ondelete="RESTRICT"), index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FitmentAuditEvent(Base):
    """Immutable audit event for all fitment mutations and decisions."""

    __tablename__ = "fitment_audit_events"
    __table_args__ = (
        UniqueConstraint("workspace_id", "event_key", name="uq_fit_audit_event_key"),
        Index("ix_fit_audit_entity", "workspace_id", "entity_type", "entity_id"),
        Index("ix_fit_audit_time", "workspace_id", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    event_key: Mapped[str] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str] = mapped_column(String(255))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FitmentSourceCapability(Base):
    """Versioned, fail-closed declaration of one source adapter capability."""

    __tablename__ = "fitment_source_capabilities"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "capability",
            "policy_version",
            name="uq_fit_source_capability_policy",
        ),
        CheckConstraint(
            "capability IN ('search_by_article', 'search_by_oe', "
            "'search_fitment', 'fetch_document')",
            name="ck_fit_source_capability_name",
        ),
        Index("ix_fit_source_capability_lookup", "source_id", "capability"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fitment_sources.id", ondelete="CASCADE"), index=True
    )
    capability: Mapped[str] = mapped_column(String(40))
    enabled: Mapped[bool] = mapped_column(Boolean)
    authentication_required: Mapped[bool] = mapped_column(Boolean)
    rate_limit: Mapped[str] = mapped_column(String(120))
    retry_policy: Mapped[dict[str, Any]] = mapped_column(JSON)
    cache_policy: Mapped[dict[str, Any]] = mapped_column(JSON)
    policy_version: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FitmentSourceReliabilitySnapshot(Base):
    """Append-only Beta posterior for a source and a concrete claim type."""

    __tablename__ = "fitment_source_reliability_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "claim_type",
            "label_event_key",
            name="uq_fit_source_beta_event",
        ),
        CheckConstraint(
            "prior_alpha > 0 AND prior_beta > 0 AND confirmed_count >= 0 "
            "AND rejected_count >= 0 AND reliability BETWEEN 0 AND 1",
            name="ck_fit_source_beta_values",
        ),
        Index(
            "ix_fit_source_beta_current",
            "source_id",
            "claim_type",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fitment_sources.id", ondelete="CASCADE"), index=True
    )
    claim_type: Mapped[str] = mapped_column(String(80))
    source_tier: Mapped[str] = mapped_column(String(1))
    prior_alpha: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    prior_beta: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    confirmed_count: Mapped[int] = mapped_column(Integer)
    rejected_count: Mapped[int] = mapped_column(Integer)
    reliability: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    label_event_key: Mapped[str] = mapped_column(String(64))
    method_version: Mapped[str] = mapped_column(String(80))
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fitment_source_reliability_snapshots.id", ondelete="RESTRICT"),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FitmentMarketRecommendation(Base):
    """Immutable advisory recommendation bound to one fitment analysis snapshot."""

    __tablename__ = "fitment_market_recommendations"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_fit_market_rec_idempotency"
        ),
        UniqueConstraint(
            "analysis_id", "input_fingerprint", name="uq_fit_market_rec_snapshot"
        ),
        CheckConstraint(
            "action IN ('consider_raise', 'hold', 'consider_reduce', "
            "'insufficient_evidence', 'manual_research_required')",
            name="ck_fit_market_rec_action",
        ),
        CheckConstraint(
            "current_price > 0 AND confidence BETWEEN 0 AND 1 "
            "AND (recommended_price IS NULL OR recommended_price > 0) "
            "AND NOT automatic_price_change_allowed",
            name="ck_fit_market_rec_safety",
        ),
        Index("ix_fit_market_rec_product_time", "catalog_item_id", "created_at"),
        Index("ix_fit_market_rec_review", "workspace_id", "action", "confidence"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fitment_analyses.id", ondelete="CASCADE"), index=True
    )
    catalog_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("catalog_items.id", ondelete="CASCADE"), index=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(64))
    input_fingerprint: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(32))
    strategy: Mapped[str] = mapped_column(String(32))
    current_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    recommended_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    recommended_range_min: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    recommended_range_max: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    absolute_change: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    relative_change: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    market_anchor: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    approved_price_floor: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3))
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    confidence_factors: Mapped[dict[str, Any]] = mapped_column(JSON)
    market_summary: Mapped[dict[str, Any]] = mapped_column(JSON)
    price_statistics: Mapped[dict[str, Any]] = mapped_column(JSON)
    candidate_decisions: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    reason_codes: Mapped[list[str]] = mapped_column(JSON)
    warnings: Mapped[list[str]] = mapped_column(JSON)
    configuration_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    contract_version: Mapped[str] = mapped_column(String(80))
    recommendation_version: Mapped[str] = mapped_column(String(80))
    automatic_price_change_allowed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FitmentRecommendationReview(Base):
    """Append-only human decision; it never publishes a marketplace price."""

    __tablename__ = "fitment_recommendation_reviews"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_fit_rec_review_idempotency"
        ),
        CheckConstraint(
            "decision IN ('accepted', 'accepted_with_modification', 'rejected', "
            "'deferred', 'research_requested')",
            name="ck_fit_rec_review_decision",
        ),
        CheckConstraint(
            "(decision IN ('accepted', 'accepted_with_modification') "
            "AND approved_price IS NOT NULL AND approved_price > 0) OR "
            "(decision NOT IN ('accepted', 'accepted_with_modification') "
            "AND approved_price IS NULL)",
            name="ck_fit_rec_review_price",
        ),
        Index("ix_fit_rec_review_time", "recommendation_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    recommendation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fitment_market_recommendations.id", ondelete="RESTRICT"), index=True
    )
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(40))
    approved_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    reason_code: Mapped[str] = mapped_column(String(80))
    comment: Mapped[str | None] = mapped_column(Text)
    recommendation_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FitmentFeedbackEvent(Base):
    """Explicit, versioned label used by the guarded learning loop."""

    __tablename__ = "fitment_feedback_events"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_fit_feedback_idempotency"
        ),
        CheckConstraint(
            "status IN ('active', 'reverted')",
            name="ck_fit_feedback_status",
        ),
        Index("ix_fit_feedback_entity", "workspace_id", "entity_type", "entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[str] = mapped_column(String(255))
    event_type: Mapped[str] = mapped_column(String(80))
    reason_code: Mapped[str] = mapped_column(String(80))
    label_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(
        String(16), default="active", server_default="active"
    )
    reverts_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("fitment_feedback_events.id", ondelete="RESTRICT"), index=True
    )
    label_version: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FitmentNotification(Base):
    """Auditable review notification payload with grouping support."""

    __tablename__ = "fitment_notifications"
    __table_args__ = (
        UniqueConstraint(
            "recommendation_id",
            "notification_type",
            name="uq_fit_notification_rec_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'delivered', 'read', 'dismissed')",
            name="ck_fit_notification_status",
        ),
        Index("ix_fit_notification_group", "workspace_id", "group_key", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    recommendation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fitment_market_recommendations.id", ondelete="CASCADE"), index=True
    )
    notification_type: Mapped[str] = mapped_column(String(80))
    group_key: Mapped[str] = mapped_column(String(120))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
