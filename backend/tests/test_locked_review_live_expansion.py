from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

import pytest

from marko.services.parser_models import Product


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "prepare_locked_review_live_expansion.py"
SPEC = importlib.util.spec_from_file_location("locked_review_live_expansion", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _seed(**overrides: str) -> dict[str, str]:
    row = {column: "" for column in MODULE.SEED_COLUMNS}
    row.update(
        {
            "our_oe": "EB5Z8005G",
            "our_title": "Радиатор Ford Explorer",
            "query": "радиатор Ford Explorer 2012 3.5",
            **overrides,
        }
    )
    return row


def _write_seed_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=MODULE.SEED_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _product() -> Product:
    return Product.from_normalized_snapshot(
        {
            "id": 3015293197,
            "name": "Радіатор кондиціонера Ford Explorer 2012",
            "sku": "EB5Z19712G",
            "brand": "Ford Motor Company",
            "price": "9999",
            "price_original": "12000",
            "discounted_price": "9999",
            "price_usd": "241.00",
            "seller_id": 4197182,
            "seller_name": "External seller",
            "image": "https://images.prom.ua/example.jpg",
            "category_ids": [0, 55, 120215],
            "is_available": True,
            "measure_unit": "шт.",
            "url": "https://prom.ua/ua/p3015293197-radiator.html",
        }
    )


def test_seed_reader_is_bounded_and_normalized_duplicate_safe(tmp_path: Path) -> None:
    path = tmp_path / "seeds.csv"
    _write_seed_csv(path, [_seed(), _seed(our_oe="EB5Z-8005-G")])

    with pytest.raises(ValueError, match="Duplicate seed OE"):
        MODULE._read_seeds(path, max_queries=2)
    with pytest.raises(ValueError, match="between 1 and 20"):
        MODULE._read_seeds(path, max_queries=21)


def test_non_monetary_capture_structurally_excludes_every_price_field() -> None:
    capture = MODULE._non_monetary_product(_product())

    assert not any("price" in key.casefold() for key in capture)
    assert capture["id"] == 3015293197
    assert capture["seller_id"] == 4197182
    assert capture["name"].startswith("Радіатор кондиціонера")


def test_review_row_contains_evidence_but_no_prediction_or_label() -> None:
    row = MODULE._review_row(_seed(), _product(), rank=1)

    assert tuple(row) == MODULE.REVIEW_COLUMNS
    assert row["rank"] == "LIVE-001"
    assert row["our_oe"] == "EB5Z8005G"
    assert row["offer_id"] == 3015293197
    assert row["offer_availability"] == "true"
    assert not any("price" in key.casefold() for key in row)
    assert not any("prediction" in key.casefold() for key in row)
    assert not any("truth" in key.casefold() for key in row)
