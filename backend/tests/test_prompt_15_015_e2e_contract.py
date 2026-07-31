"""Static and pure-fixture proof for the isolated PROMPT_15_015 E2E harness."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

import yaml

from marko.e2e.fixture_seed import DEFAULT_FIXTURE, _load_fixture, _target_output
from metis.pricing import (
    comparison_evidence_from_dict,
    evaluate_comparison_evidence,
)


ROOT = Path(__file__).resolve().parents[2]


def _runner_module() -> ModuleType:
    path = ROOT / "scripts/run_prompt_15_015_e2e.py"
    spec = importlib.util.spec_from_file_location("prompt_15_015_e2e_runner", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_e2e_compose_is_isolated_and_live_source_is_fail_closed() -> None:
    e2e = yaml.safe_load((ROOT / "compose.e2e.yaml").read_text(encoding="utf-8"))
    environment = e2e["x-e2e-backend-environment"]
    assert environment["ENVIRONMENT"] == "e2e"
    assert environment["E2E_AUTH_BYPASS"] == "true"
    assert environment["PROM_MARKETPLACE_SOURCE_ACCESS_VERDICT"] == "NOT_PERMITTED"
    assert environment["PRICING_BRAND_TIERS_PATH"] == (
        "/app/src/marko/e2e/fixtures/brands.yaml"
    )
    assert environment["PRICING_V3_ROBUST_DISPERSION_ENABLED"] == "false"
    assert environment["PRICING_COMPARABILITY_V1_AUTOMATIC_ENABLED"] == "false"
    assert set(e2e["services"]) >= {
        "db",
        "broker",
        "migrate",
        "api",
        "worker",
        "store-sync-worker",
        "pricing-worker",
        "scheduler",
        "frontend",
        "browser-e2e",
    }
    assert e2e["services"]["browser-e2e"]["profiles"] == ["e2e"]


def test_production_manifest_hard_disables_e2e_auth() -> None:
    production = yaml.safe_load(
        (ROOT / "deploy/compose.production.yaml").read_text(encoding="utf-8")
    )
    environment = production["x-backend-environment"]
    assert environment["ENVIRONMENT"] == "production"
    assert environment["E2E_AUTH_BYPASS"] == "false"
    assert environment["E2E_AUTH_TOKEN"] == ""
    assert environment["PRICING_BRAND_TIERS_PATH"] == (
        "${PRICING_BRAND_TIERS_PATH:-/app/config/brands.yaml}"
    )


def test_host_runner_has_full_failure_matrix_and_scoped_cleanup() -> None:
    source = (ROOT / "scripts/run_prompt_15_015_e2e.py").read_text(encoding="utf-8")
    for index in range(1, 11):
        assert f"E2E-F{index:02d}" in source
    assert (
        '"down",\n                "--volumes",\n                "--remove-orphans"'
        in source
    )
    assert "system prune" not in source
    assert "volume prune" not in source
    assert "container prune" not in source


def test_host_runner_previews_catalog_before_importing_selected_sheet() -> None:
    source = (ROOT / "scripts/run_prompt_15_015_e2e.py").read_text(encoding="utf-8")

    preview_index = source.index('f"{api_url}/api/v1/catalog/imports/preview"')
    import_index = source.index('f"{api_url}/api/v1/catalog/imports"', preview_index)

    assert preview_index < import_index
    assert '"sheet_name": selected_sheet["name"]' in source
    assert 'if sheet["is_catalog_candidate"]' in source


def test_host_runner_proves_duplicate_scheduler_is_fenced_without_waiting_for_exit() -> None:
    source = (ROOT / "scripts/run_prompt_15_015_e2e.py").read_text(encoding="utf-8")

    assert '"run", "-d", "--no-deps", "scheduler"' in source
    assert "scheduler_singleton_lock_unavailable" in source
    assert '"docker", "rm", "--force", duplicate_scheduler_container' in source
    assert "second_scheduler.returncode == 75" not in source


def test_e2e_probe_counts_physical_network_attempts_not_replay_requests() -> None:
    source = (ROOT / "backend/src/marko/e2e/probe.py").read_text(encoding="utf-8")

    assert "select(func.count(ScrapeHttpAttempt.id))" in source
    assert '"live_network_request_count": physical_http_attempt_count' in source
    assert 'kind in {"product_page", "search_page", "seller_page"}' not in source


def test_full_preflight_proof_is_tls_equivalent_and_scoped() -> None:
    source = (ROOT / "scripts/run_prompt_15_015_preflight_proof.py").read_text(
        encoding="utf-8"
    )

    assert 'POSTGRES_IMAGE = "postgres:17-alpine"' in source
    assert 'REDIS_IMAGE = "redis:8-alpine"' in source
    assert '"--tls-port"' in source
    assert 'mode="full"' in source
    assert '"docker", "rm", "--force", container' in source
    assert "system prune" not in source
    assert "volume prune" not in source


def test_browser_harness_uses_valid_explicit_locale_and_captures_errors() -> None:
    source = (ROOT / "e2e/browser/run.mjs").read_text(encoding="utf-8")

    assert "locale: 'ru-RU'" in source
    assert "visibleText('Сравнение цен', 'BROWSER_PAGE_RENDERED')" in source
    assert "evaluate((element) => element.click())" in source
    assert ".getByLabel(text, { exact: false })" in source
    assert ".or(page.getByText(text, { exact: false }))" in source
    assert "getByRole('button', { name: 'Принять', exact: true })" in source
    assert "page.on('pageerror'" in source
    assert "page.on('requestfailed'" in source


def test_browser_harness_executes_operator_workflow_after_host_fault_checks() -> None:
    browser_source = (ROOT / "e2e/browser/run.mjs").read_text(encoding="utf-8")
    host_source = (ROOT / "scripts/run_prompt_15_015_e2e.py").read_text(
        encoding="utf-8"
    )

    marker = "host-business-checks-complete"
    assert marker in browser_source
    assert marker in host_source
    assert "browser-container-state.json" in host_source
    assert "browser-container.log" in host_source
    assert "waitForArtifactMarker" in browser_source
    assert "`${frontendUrl}/#/${tab}`" in browser_source
    assert "setFiles('/artifacts/ui-catalog-fixture.xlsx')" in browser_source
    assert '"ui_catalog_xlsx": ui_catalog_hash' in host_source
    assert "BROWSER_CATALOG_SHEET_SELECTED" in browser_source
    assert "Catalog · 3 строк" in browser_source
    assert "BROWSER_CATALOG_IMPORT_PARTIAL" in browser_source
    assert "BROWSER_CATALOG_IMPORT_COUNTS" in browser_source
    assert "BROWSER_EXPORT_CSV_SELECTED" in browser_source
    assert "BROWSER_EXPORT_CONTROL_VISIBLE" in browser_source
    assert "coordinate within Flutter disabled popup semantics container" in browser_source
    assert "BROWSER_EXPORT_DOWNLOADED" in browser_source
    assert "waitForResponse" in browser_source
    assert "const responsePromise = waitForCsvExport(30000)" in browser_source
    assert "content-disposition" in browser_source
    assert "page.setViewportSize({ width: 375, height: 812 })" in browser_source
    assert "BROWSER_PRICING_RUN_STARTED" in browser_source
    assert "BROWSER_PRICING_RUN_FINISHED" in browser_source
    assert "ui-pricing-run.json" in browser_source
    assert "ui-pricing-run.json" in host_source
    assert '"stop", "pricing-worker"' in host_source
    assert '"start", "pricing-worker"' in host_source
    assert "BROWSER_UKRAINIAN_LOCALE" in browser_source
    assert "browser-mobile-uk.png" in browser_source


def test_headless_export_skips_only_the_native_save_dialog_in_e2e_builds() -> None:
    source = (
        ROOT / "frontend/lib/features/pricing/recommendation_export_button.dart"
    ).read_text(encoding="utf-8")

    assert "Environment.e2eMode ? _acknowledgeE2eDownload : _saveDownload" in source
    assert "FilePicker.saveFile(" in source


def test_ui_pricing_run_uses_fixture_route_only_in_e2e_builds() -> None:
    source = (ROOT / "frontend/lib/features/pricing/pricing_api.dart").read_text(
        encoding="utf-8"
    )

    assert "Environment.e2eMode" in source
    assert "'/api/v1/e2e/pricing/runs'" in source
    assert "'/api/v1/pricing/runs'" in source


def test_blocked_evidence_never_claims_unexecuted_e2e() -> None:
    module = _runner_module()
    evidence = module._blocked_evidence(
        "DOCKER_BINARY_NOT_AVAILABLE",
        {"python": "test", "docker": "NOT_AVAILABLE", "compose": "NOT_AVAILABLE"},
    )["e2e_evidence"]
    assert evidence["status"] == "BLOCKED_ENVIRONMENT"
    assert evidence["cleanup_complete"] is True
    assert evidence["live_prom_requests"] == 0
    assert evidence["automatic_price_applications"] == 0
    assert len(evidence["failure_injection_results"]) == 10
    assert all(
        item["status"] == "NOT_RUN" for item in evidence["failure_injection_results"]
    )


def test_replay_fixture_produces_verified_structured_evidence_without_network() -> None:
    fixture, _, fixture_hash = _load_fixture(DEFAULT_FIXTURE)
    target = SimpleNamespace(
        query="1K0698151",
        adapter_version="prom-adapter-v1",
        original_url="https://fixture.invalid/original",
        canonical_url="https://fixture.invalid/canonical",
        product_key="fixture-product",
        input_hash="0" * 64,
    )
    output = _target_output(target, fixture, fixture_hash)
    records = output.payload["output"]["records"]
    assert len(records) == len(fixture["offers"])
    assert all(record["retrieval_score"] is None for record in records)
    for record in records:
        offer = record["product"]
        evidence = comparison_evidence_from_dict(record["upstream_comparison_evidence"])
        decision = evaluate_comparison_evidence(
            evidence,
            seller_id=offer["seller_id"],
            currency_raw=offer["currency"],
            currency_normalized=offer["currency"],
            required_currency="UAH",
            category="brakes",
        )
        assert decision.automatic_eligible
        assert evidence is not None
        assert evidence.provenance.source_type == "persisted_replay"
        assert evidence.provenance.raw_evidence_sha256 == fixture_hash
