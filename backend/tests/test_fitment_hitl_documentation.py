from __future__ import annotations

from pathlib import Path
import re

from metis.fitment import FITMENT_CONTRACT_VERSION, FITMENT_SCORING_VERSION
from metis.fitment.hitl import (
    HITL_MARKET_CONTRACT_VERSION,
    HITL_RECOMMENDATION_VERSION,
)


DOCUMENT = (
    Path(__file__).parents[2]
    / "docs"
    / "METIS_HITL_COMPETITIVE_PRICING_IMPLEMENTATION_2026-07-21.md"
)


def test_hitl_implementation_document_has_all_43_required_sections() -> None:
    text = DOCUMENT.read_text(encoding="utf-8")
    section_numbers = [
        int(value)
        for value in re.findall(r"^## ([1-9][0-9]?)\. ", text, flags=re.MULTILINE)
    ]

    assert section_numbers == list(range(1, 44))
    assert text.count("```mermaid") >= 3
    assert "erDiagram" in text
    assert "sequenceDiagram" in text
    assert "stateDiagram-v2" in text


def test_hitl_document_versions_and_technical_contracts_match_code() -> None:
    text = DOCUMENT.read_text(encoding="utf-8")

    for version in (
        FITMENT_CONTRACT_VERSION,
        FITMENT_SCORING_VERSION,
        HITL_MARKET_CONTRACT_VERSION,
        HITL_RECOMMENDATION_VERSION,
    ):
        assert f"`{version}`" in text
    for required in (
        "n_eff = (sum W_j)^2 / sum(W_j^2)",
        "class SourceAdapter(Protocol)",
        "source_not_permitted",
        "automatic_price_change_allowed",
        "representative: false",
        "7zap network adapter не активируется",
        "## 43. Production Readiness Checklist",
    ):
        assert required in text
