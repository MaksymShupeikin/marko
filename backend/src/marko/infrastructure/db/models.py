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
