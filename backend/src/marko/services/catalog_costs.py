"""Tenant-scoped append-only storage for encrypted catalog unit cost."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from marko.core.config import Settings, get_settings
from marko.core.cost_encryption import EncryptedCost, decrypt_cost, encrypt_cost
from marko.infrastructure.db.models import CatalogItemCostRecord
from marko.services.cost_privacy import (
    CostPrivacyBlocked,
    CostPrivacyMode,
    require_server_cost_input_allowed,
)


async def get_latest_cost_record(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    catalog_item_id: UUID,
) -> CatalogItemCostRecord | None:
    return await session.scalar(
        select(CatalogItemCostRecord)
        .where(
            CatalogItemCostRecord.workspace_id == workspace_id,
            CatalogItemCostRecord.catalog_item_id == catalog_item_id,
        )
        .order_by(CatalogItemCostRecord.sequence_no.desc())
        .limit(1)
    )


async def cost_configuration_map(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    catalog_item_ids: Iterable[UUID],
) -> dict[UUID, bool]:
    ids = tuple(dict.fromkeys(catalog_item_ids))
    if not ids:
        return {}
    ranked = (
        select(
            CatalogItemCostRecord.catalog_item_id.label("catalog_item_id"),
            CatalogItemCostRecord.action.label("action"),
            func.row_number()
            .over(
                partition_by=CatalogItemCostRecord.catalog_item_id,
                order_by=CatalogItemCostRecord.sequence_no.desc(),
            )
            .label("row_position"),
        )
        .where(
            CatalogItemCostRecord.workspace_id == workspace_id,
            CatalogItemCostRecord.catalog_item_id.in_(ids),
        )
        .subquery()
    )
    result = {item_id: False for item_id in ids}
    rows = (
        await session.execute(
            select(ranked.c.catalog_item_id, ranked.c.action).where(
                ranked.c.row_position == 1
            )
        )
    ).all()
    for catalog_item_id, action in rows:
        result[catalog_item_id] = action == "SET"
    return result


def add_encrypted_cost_record(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    catalog_item_id: UUID,
    user_id: UUID,
    cost: Decimal,
    reason: str,
    settings: Settings | None = None,
) -> CatalogItemCostRecord:
    selected = settings or get_settings()
    require_server_cost_input_allowed(cost, settings=selected)
    record_id = uuid4()
    encrypted = encrypt_cost(
        cost,
        workspace_id=workspace_id,
        catalog_item_id=catalog_item_id,
        record_id=record_id,
        keyring=selected.cost_keyring,
    )
    record = CatalogItemCostRecord(
        id=record_id,
        workspace_id=workspace_id,
        catalog_item_id=catalog_item_id,
        user_id=user_id,
        action="SET",
        ciphertext=encrypted.ciphertext,
        nonce=encrypted.nonce,
        key_id=encrypted.key_id,
        algorithm=encrypted.algorithm,
        format_version=encrypted.format_version,
        reason=reason,
    )
    session.add(record)
    return record


def add_cost_clear_record(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    catalog_item_id: UUID,
    user_id: UUID,
    reason: str,
    settings: Settings | None = None,
) -> CatalogItemCostRecord:
    selected = settings or get_settings()
    if (
        CostPrivacyMode(selected.cost_privacy_mode)
        != CostPrivacyMode.SERVER_SIDE_ENCRYPTED
    ):
        raise CostPrivacyBlocked(
            "Clearing server-side cost requires SERVER_SIDE_ENCRYPTED mode"
        )
    selected.cost_keyring
    record = CatalogItemCostRecord(
        id=uuid4(),
        workspace_id=workspace_id,
        catalog_item_id=catalog_item_id,
        user_id=user_id,
        action="CLEAR",
        ciphertext=None,
        nonce=None,
        key_id=None,
        algorithm=None,
        format_version=None,
        reason=reason,
    )
    session.add(record)
    return record


async def get_decrypted_catalog_cost(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    catalog_item_id: UUID,
    settings: Settings | None = None,
) -> Decimal | None:
    record = await get_latest_cost_record(
        session,
        workspace_id=workspace_id,
        catalog_item_id=catalog_item_id,
    )
    if record is None or record.action == "CLEAR":
        return None
    selected = settings or get_settings()
    if (
        CostPrivacyMode(selected.cost_privacy_mode)
        != CostPrivacyMode.SERVER_SIDE_ENCRYPTED
    ):
        raise CostPrivacyBlocked(
            "Encrypted cost exists but SERVER_SIDE_ENCRYPTED mode is disabled"
        )
    if any(
        value is None
        for value in (
            record.ciphertext,
            record.nonce,
            record.key_id,
            record.algorithm,
            record.format_version,
        )
    ):
        raise CostPrivacyBlocked("Encrypted cost record is incomplete")
    return decrypt_cost(
        EncryptedCost(
            ciphertext=record.ciphertext,
            nonce=record.nonce,
            key_id=record.key_id,
            algorithm=record.algorithm,
            format_version=record.format_version,
        ),
        workspace_id=workspace_id,
        catalog_item_id=catalog_item_id,
        record_id=record.id,
        keyring=selected.cost_keyring,
    )


__all__ = [
    "add_cost_clear_record",
    "add_encrypted_cost_record",
    "cost_configuration_map",
    "get_decrypted_catalog_cost",
    "get_latest_cost_record",
]
