#!/usr/bin/env python3
"""Prove the encrypted-cost persistence path against a non-production database.

The proof generates an ephemeral in-memory key, writes one synthetic value in a
transaction, authenticates and decrypts it through the application service, and
rolls the transaction back.  It never prints the key or leaves a cost record.
"""

from __future__ import annotations

import asyncio
import base64
from decimal import Decimal
import json
import secrets
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from marko.core.config import Settings, get_settings
from marko.infrastructure.db.models import (
    CatalogImportBatch,
    CatalogItem,
    CatalogItemCostRecord,
    User,
    Workspace,
)
from marko.services.catalog_costs import (
    add_cost_clear_record,
    add_encrypted_cost_record,
    cost_configuration_map,
    get_decrypted_catalog_cost,
)


async def prove() -> None:
    base = get_settings()
    if base.is_production:
        raise RuntimeError("Encrypted-cost runtime proof is forbidden in production")

    key_id = "runtime-proof-v1"
    encoded_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    settings = Settings(
        database_url=base.database_url,
        cost_privacy_mode="SERVER_SIDE_ENCRYPTED",
        cost_encryption_active_key_id=key_id,
        cost_encryption_keys_json=json.dumps({key_id: encoded_key}),
    )
    engine = create_async_engine(base.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with sessions() as session:
            before = await session.scalar(select(func.count(CatalogItemCostRecord.id)))
            suffix = secrets.token_hex(6)
            workspace = Workspace(
                name="Encrypted cost runtime proof",
                slug=f"encrypted-cost-proof-{suffix}",
            )
            user = User(email=f"encrypted-cost-proof-{suffix}@example.invalid")
            session.add_all([workspace, user])
            await session.flush()
            batch = CatalogImportBatch(
                workspace_id=workspace.id,
                filename="synthetic-runtime-proof.xlsx",
                content_sha256="0" * 64,
                content_size=1,
                column_mapping={},
            )
            session.add(batch)
            await session.flush()
            item = CatalogItem(
                workspace_id=workspace.id,
                import_batch_id=batch.id,
                source_row=1,
                sku=f"PROOF-{suffix}",
                oe_raw="PROOF-OE",
                oe_norm="PROOFOE",
                name="Synthetic encrypted cost proof item",
                category="runtime-proof",
                current_price=Decimal("1000.00"),
                raw_row={},
            )
            session.add(item)
            await session.flush()

            record = add_encrypted_cost_record(
                session,
                workspace_id=item.workspace_id,
                catalog_item_id=item.id,
                user_id=user.id,
                cost=Decimal("987.65"),
                reason="synthetic rollback-only runtime proof",
                settings=settings,
            )
            await session.flush()
            assert record.sequence_no > 0
            assert record.ciphertext is not None
            assert b"987.65" not in record.ciphertext
            assert (
                await get_decrypted_catalog_cost(
                    session,
                    workspace_id=item.workspace_id,
                    catalog_item_id=item.id,
                    settings=settings,
                )
                == Decimal("987.65")
            )
            configured = await cost_configuration_map(
                session,
                workspace_id=item.workspace_id,
                catalog_item_ids=[item.id],
            )
            assert configured == {item.id: True}
            assert (
                await get_decrypted_catalog_cost(
                    session,
                    workspace_id=uuid4(),
                    catalog_item_id=item.id,
                    settings=settings,
                )
                is None
            )
            cleared = add_cost_clear_record(
                session,
                workspace_id=item.workspace_id,
                catalog_item_id=item.id,
                user_id=user.id,
                reason="synthetic rollback-only clear proof",
                settings=settings,
            )
            await session.flush()
            assert cleared.sequence_no > record.sequence_no
            assert (
                await get_decrypted_catalog_cost(
                    session,
                    workspace_id=item.workspace_id,
                    catalog_item_id=item.id,
                    settings=settings,
                )
                is None
            )
            configured_after_clear = await cost_configuration_map(
                session,
                workspace_id=item.workspace_id,
                catalog_item_ids=[item.id],
            )
            assert configured_after_clear == {item.id: False}
            await session.rollback()

        async with sessions() as session:
            after = await session.scalar(select(func.count(CatalogItemCostRecord.id)))
        assert after == before
    finally:
        await engine.dispose()

    print("RUNTIME_ENCRYPTED_COST_TRANSACTION_PASS")
    print("PERSISTED_SYNTHETIC_RECORDS=0")
    print("KEY_MATERIAL_PRINTED=false")


if __name__ == "__main__":
    asyncio.run(prove())
