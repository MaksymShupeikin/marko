from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from marko.services.attention import (
    _assessment_values,
    _severity,
    _target_characteristics,
    mark_run_attention_processing,
    mark_source_monitoring_failed,
)
from marko.services.unified_catalog import _ensure_attention_items, xlsx_source_id


def test_xlsx_source_identity_is_stable_per_workspace_and_filename() -> None:
    workspace_id = uuid4()

    first = xlsx_source_id(workspace_id=workspace_id, filename=" Catalog.XLSX ")
    second = xlsx_source_id(workspace_id=workspace_id, filename="catalog.xlsx")

    assert first == second
    assert first != xlsx_source_id(
        workspace_id=uuid4(),
        filename="catalog.xlsx",
    )


def test_attention_uses_advisory_price_action_without_hiding_review_gate() -> None:
    computed_at = datetime.now(UTC)
    product = SimpleNamespace(current_price=Decimal("80"))
    recommendation = SimpleNamespace(
        id=uuid4(),
        action="MANUAL_REVIEW",
        recommended_price=None,
        lower_bound=None,
        upper_bound=None,
        confidence=Decimal("0.72"),
        verified_seller_count=4,
        reason_codes=["ACTIVATION_GATE_REVIEW"],
        computed_at=computed_at,
        calculation_trace={
            "advisory_decision": {
                "action": "RAISE",
                "recommended_price": "100",
                "target_band_low": "95",
                "target_band_high": "105",
            }
        },
    )

    result = _assessment_values(product, recommendation)

    assert result["status"] == "UNDERPRICED"
    assert result["suggested_price"] == Decimal("100")
    assert result["market_low"] == Decimal("95")
    assert result["market_high"] == Decimal("105")
    assert result["difference_percent"] == Decimal("-20")
    assert result["evidence_count"] == 4
    assert result["market_checked_at"] == computed_at
    assert result["reason_codes"] == [
        "ACTIVATION_GATE_REVIEW",
        "ADVISORY_REQUIRES_REVIEW",
    ]


def test_attention_fails_closed_when_pricing_produces_no_result() -> None:
    result = _assessment_values(
        SimpleNamespace(current_price=Decimal("150")),
        None,
    )

    assert result["status"] == "NO_DATA"
    assert result["suggested_price"] is None
    assert result["confidence"] == Decimal("0")
    assert result["reason_codes"] == ["PRICING_RESULT_NOT_PRODUCED"]


def test_attention_market_range_uses_only_confirmed_target_market_offers() -> None:
    result = _assessment_values(
        SimpleNamespace(current_price=Decimal("130")),
        SimpleNamespace(
            id=uuid4(),
            action="LOWER",
            recommended_price=Decimal("110"),
            lower_bound=Decimal("90"),
            upper_bound=Decimal("140"),
            confidence=Decimal("0.8"),
            verified_seller_count=2,
            reason_codes=[],
            computed_at=datetime.now(UTC),
            calculation_trace={
                "normalized_offers": [
                    {"cohort_role": "TARGET_MARKET", "normalized_price": "101"},
                    {"cohort_role": "TARGET_MARKET", "normalized_price": "119"},
                    {"cohort_role": "USED_REJECTED", "normalized_price": "12"},
                ]
            },
        ),
    )

    assert result["status"] == "OVERPRICED"
    assert result["market_low"] == Decimal("101")
    assert result["market_high"] == Decimal("119")


def test_attention_severity_is_bounded_and_review_stays_visible() -> None:
    assert _severity("OVERPRICED", Decimal("142")) == 100
    assert _severity("UNDERPRICED", Decimal("-17.9")) == 17
    assert _severity("REVIEW_REQUIRED", None) == 60
    assert _severity("IN_MARKET", Decimal("1")) == 0


def test_prom_snapshot_preserves_quality_and_fitment_characteristics() -> None:
    result = _target_characteristics(
        {
            "characteristics": [
                {"name": "Материал", "value": "керамика"},
                {"name": "Качество", "value": "премиум"},
            ],
            "condition": "new",
            "package_quantity": 2,
            "position": "front",
        }
    )

    assert result == {
        "Материал": "керамика",
        "Качество": "премиум",
        "condition": "new",
        "package_quantity": 2,
        "position": "front",
    }


class _ScalarRows:
    def __init__(self, values) -> None:
        self.values = values

    def all(self):
        return self.values


class _AttentionSession:
    def __init__(self, attention_items) -> None:
        self.attention_items = attention_items
        self.added = []

    async def scalars(self, _statement):
        return _ScalarRows(self.attention_items)

    def add(self, value) -> None:
        self.added.append(value)


class _MonitoringFailureSession:
    def __init__(self, product_ids, attention_items) -> None:
        self.results = [product_ids, attention_items]

    async def scalars(self, _statement):
        return _ScalarRows(self.results.pop(0))


class _MonitoringStartedSession:
    def __init__(self, run, products, attention_items) -> None:
        self.run = run
        self.results = [products, attention_items]
        self.added = []

    async def get(self, _model, _identifier):
        return self.run

    async def scalars(self, _statement):
        return _ScalarRows(self.results.pop(0))

    def add(self, value) -> None:
        self.added.append(value)


async def test_unavailable_product_leaves_queue_and_reopens_when_it_returns() -> None:
    product_id = uuid4()
    workspace_id = uuid4()
    product = SimpleNamespace(
        id=product_id,
        workspace_id=workspace_id,
        current_price=Decimal("100"),
        oe_norm="OE123",
        is_available=False,
    )
    attention = SimpleNamespace(
        product_id=product_id,
        status="OVERPRICED",
        severity=40,
        review_state="OPEN",
    )
    session = _AttentionSession([attention])

    await _ensure_attention_items(session, [product])  # type: ignore[arg-type]

    assert attention.status == "REVIEW_REQUIRED"
    assert attention.severity == 0
    assert attention.review_state == "RESOLVED"

    product.is_available = True
    await _ensure_attention_items(session, [product])  # type: ignore[arg-type]

    assert attention.status == "PROCESSING"
    assert attention.severity == 0
    assert attention.review_state == "OPEN"


async def test_failed_automatic_start_does_not_leave_products_processing() -> None:
    product_id = uuid4()
    attention = SimpleNamespace(
        status="PROCESSING",
        severity=0,
        review_state="OPEN",
    )
    session = _MonitoringFailureSession([product_id], [attention])

    changed = await mark_source_monitoring_failed(
        session,  # type: ignore[arg-type]
        workspace_id=uuid4(),
        source_kind="XLSX",
        source_id=uuid4(),
    )

    assert changed == 1
    assert attention.status == "REVIEW_REQUIRED"
    assert attention.severity == 60


async def test_started_monitoring_reopens_products_as_processing() -> None:
    product_id = uuid4()
    product = SimpleNamespace(id=product_id, workspace_id=uuid4())
    attention = SimpleNamespace(
        product_id=product_id,
        status="REVIEW_REQUIRED",
        severity=60,
        review_state="OPEN",
    )
    session = _MonitoringStartedSession(
        SimpleNamespace(workspace_id=product.workspace_id, import_batch_id=uuid4()),
        [product],
        [attention],
    )

    changed = await mark_run_attention_processing(
        session,  # type: ignore[arg-type]
        uuid4(),
    )

    assert changed == 1
    assert attention.status == "PROCESSING"
    assert attention.severity == 0
    assert attention.review_state == "OPEN"
