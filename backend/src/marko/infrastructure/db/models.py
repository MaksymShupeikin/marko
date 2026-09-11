"""Relational persistence models for accounts, listings, prices, and matches."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
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


class SyncStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    firebase_uid: Mapped[str | None] = mapped_column(
        String(128), unique=True, index=True
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(160))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class Workspace(TimestampMixin, Base):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160))
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    # Пейвол: скільки перевірок цін уже витрачено на цей воркспейс.
    checks_used: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    # Білий список: постійний доступ без підписки (оновлюється вручну в БД).
    has_free_access: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    # Коли воркспейс попросив повний доступ (null = не просив). Перший запит
    # фіксується назавжди, повторні — no-op, тож дублів не буває.
    access_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
    """Один магазин у межах воркспейсу.

    Лістинги висять на store_id, тож спільний рядок магазину означав би спільний
    каталог: чужий імпорт того самого продавця протікав би в інший акаунт.
    """

    __tablename__ = "marketplace_stores"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "marketplace",
            "external_id",
            name="uq_store_workspace_marketplace_external",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    marketplace: Mapped[str] = mapped_column(String(32), default="prom", server_default="prom")
    external_id: Mapped[str] = mapped_column(String(100))
    name: Mapped[str | None] = mapped_column(String(255))
    canonical_url: Mapped[str] = mapped_column(Text)
    logo_url: Mapped[str | None] = mapped_column(Text)
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


class CompetitorSellerExclusion(TimestampMixin, Base):
    """A Prom seller that must never be treated as a competitor in a workspace.

    This identity deliberately outlives ``MarketplaceStore``. Removing an
    imported catalog must not turn the seller's offers into market prices.
    """

    __tablename__ = "competitor_seller_exclusions"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "marketplace",
            "external_id",
            name="uq_competitor_seller_exclusion_identity",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    marketplace: Mapped[str] = mapped_column(
        String(32), default="prom", server_default="prom"
    )
    external_id: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str | None] = mapped_column(String(255))
    canonical_url: Mapped[str] = mapped_column(Text)


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
    currency: Mapped[str] = mapped_column(String(3), default="UAH", server_default="UAH")
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


class WorkspaceListingOverride(TimestampMixin, Base):
    """Workspace-local catalog edits layered over a shared source listing."""

    __tablename__ = "workspace_listing_overrides"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    listing_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    name: Mapped[str | None] = mapped_column(Text)
    sku: Mapped[str | None] = mapped_column(String(255))
    brand: Mapped[str | None] = mapped_column(String(255))
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    is_available: Mapped[bool | None] = mapped_column(Boolean)
    image_url: Mapped[str | None] = mapped_column(Text)
    oem_numbers: Mapped[list[str] | None] = mapped_column(JSON)
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    # Останнє перечитування сторінки товару. updated_at рухає будь-яка правка,
    # тому час синхронізації живе окремо.
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PriceObservation(Base):
    __tablename__ = "price_observations"
    __table_args__ = (
        Index("ix_price_observation_listing_time", "listing_id", "observed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    listing_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), index=True
    )
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3))
    is_available: Mapped[bool | None] = mapped_column(Boolean)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SyncRun(TimestampMixin, Base):
    __tablename__ = "sync_runs"
    __table_args__ = (Index("ix_sync_run_workspace_status", "workspace_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    store_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("marketplace_stores.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str] = mapped_column(String(50))
    status: Mapped[SyncStatus] = mapped_column(
        Enum(SyncStatus, name="sync_status"), default=SyncStatus.queued
    )
    task_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    progress_current: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    progress_total: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RepriceScope(str, enum.Enum):
    full = "full"
    partial = "partial"


class RepriceMode(str, enum.Enum):
    fresh = "fresh"
    resume = "resume"


class RepricePolicy(str, enum.Enum):
    aggressive = "aggressive"
    balanced = "balanced"
    hold_margin = "hold_margin"


class RepriceOutcome(str, enum.Enum):
    changed = "changed"
    unchanged = "unchanged"
    no_recommendation = "no_recommendation"


class RepriceItemStatus(str, enum.Enum):
    pending = "pending"
    done = "done"
    failed = "failed"


class RepriceRun(TimestampMixin, Base):
    """One repricing pass over a slice of the workspace catalog.

    Прогрес і скасування живуть у ``SyncRun`` — той самий механізм, що й в
    імпорту з оновленням каталогу. Тут лише те, чого в ньому немає: з чим
    саме звіряли, скільки товарів просили і що вийшло.
    """

    __tablename__ = "reprice_runs"
    __table_args__ = (
        Index("ix_reprice_run_workspace_created", "workspace_id", "created_at"),
        Index("ix_reprice_run_catalog_signature", "catalog_scope_signature"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    # Прогрес і скасування — через /jobs, тож запуск має власний SyncRun.
    sync_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sync_runs.id", ondelete="SET NULL"), index=True
    )

    scope: Mapped[RepriceScope] = mapped_column(
        Enum(RepriceScope, name="reprice_scope"), default=RepriceScope.partial
    )
    mode: Mapped[RepriceMode] = mapped_column(
        Enum(RepriceMode, name="reprice_mode"), default=RepriceMode.fresh
    )
    policy: Mapped[RepricePolicy] = mapped_column(
        Enum(RepricePolicy, name="reprice_policy"), default=RepricePolicy.balanced
    )
    # Чим сортували план: поки одна стратегія, але запуск має пам'ятати свою.
    order_strategy: Mapped[str] = mapped_column(
        String(32), default="value_at_risk", server_default="value_at_risk"
    )
    requested_count: Mapped[int | None] = mapped_column(Integer)
    engine: Mapped[str] = mapped_column(String(64), default="legacy_min_minus")

    # Підпис складу каталогу, а не його цін: див. reprice_catalog_signature.
    catalog_scope_signature: Mapped[str] = mapped_column(String(40))
    catalog_item_count: Mapped[int] = mapped_column(Integer, default=0)
    store_ids: Mapped[list[str] | None] = mapped_column(JSON)
    filter_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    changed_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    unchanged_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class RepriceRunItem(TimestampMixin, Base):
    """One product inside a repricing run, with the evidence behind its price."""

    __tablename__ = "reprice_run_items"
    __table_args__ = (
        Index("ix_reprice_item_run_position", "run_id", "position"),
        Index("ix_reprice_item_listing", "listing_id"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reprice_runs.id", ondelete="CASCADE"), primary_key=True
    )
    listing_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("listings.id", ondelete="CASCADE"), primary_key=True
    )
    # Порядок плану: за ним «продовжити» знає, де зупинилися.
    position: Mapped[int] = mapped_column(Integer, default=0)
    # Нормалізований артикул: запасний шлях звірки, коли listing_id змінився.
    group_key: Mapped[str | None] = mapped_column(String(255))

    status: Mapped[RepriceItemStatus] = mapped_column(
        Enum(RepriceItemStatus, name="reprice_item_status"),
        default=RepriceItemStatus.pending,
    )
    outcome: Mapped[RepriceOutcome | None] = mapped_column(
        Enum(RepriceOutcome, name="reprice_outcome")
    )
    # Чому не порахували: «тонкий ринок», «спрацювало обмеження» тощо.
    reason: Mapped[str | None] = mapped_column(String(255))

    old_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    new_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    delta_abs: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    delta_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    # Ціна товару на момент розрахунку: застарівання відстежуємо по товару,
    # а не по каталогу цілком.
    price_at_compute: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    zone: Mapped[str | None] = mapped_column(String(32))
    tier: Mapped[str | None] = mapped_column(String(32))
    method: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    offers_total: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Приховано зі звіту користувачем: товар у каталозі не чіпаємо.
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
