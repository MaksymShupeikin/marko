from __future__ import annotations

import json
import os

import pytest
from sqlalchemy import text

from marko.infrastructure.db.session import async_session_factory
from marko.services.catalog_identity_safety import is_internal_catalog_code
from marko.services.xlsx_catalog import normalize_identifier


pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        os.getenv("MARKO_RUN_POSTGRES_INTEGRATION") != "1",
        reason=(
            "set MARKO_RUN_POSTGRES_INTEGRATION=1 with a disposable PostgreSQL database"
        ),
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("part_numbers", "expected_code", "expected_count"),
    (
        (["056121113D", "050121113C", "776416"], "776416", 1),
        (["056121113D", "050121113C"], "", 0),
        (["776416", "776440"], "", 2),
        (["776 416", "776-416"], "776416", 1),
        # Observed on the customer's Prom export: a Cyrillic "\u0441" where the
        # catalogue row carries a Latin "C".  Both sides must fold to one key.
        (["77643352\u0441"], "77643352C", 1),
        (["77643352\u0441", "77643352C"], "77643352C", 1),
        (None, "", 0),
    ),
)
async def test_generated_function_extracts_only_one_unambiguous_private_code(
    part_numbers: list[str] | None,
    expected_code: str,
    expected_count: int,
) -> None:
    payload = {} if part_numbers is None else {"part_numbers": part_numbers}
    async with async_session_factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT public.marko_listing_internal_code(CAST(:payload AS json)) "
                    "AS code, "
                    "public.marko_listing_internal_code_count(CAST(:payload AS json)) "
                    "AS count"
                ),
                {"payload": json.dumps(payload)},
            )
        ).one()

    assert row.code == expected_code
    assert row.count == expected_count


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw", ("7764 586", "776-440", " 776440 ", "77643352\u0441", "77643899VP12")
)
async def test_sql_and_python_normalization_agree_on_observed_export_forms(
    raw: str,
) -> None:
    async with async_session_factory() as session:
        sql_value = await session.scalar(
            text("SELECT public.marko_listing_internal_code(CAST(:payload AS json))"),
            {"payload": json.dumps({"part_numbers": [raw]})},
        )

    assert is_internal_catalog_code(raw) is True
    assert sql_value == normalize_identifier(raw)
