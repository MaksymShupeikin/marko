"""Environment-based application configuration."""

from __future__ import annotations

from decimal import Decimal
from functools import cached_property, lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from marko.core.ai_model_identity import is_immutable_model_snapshot
from marko.core.cost_encryption import CostKeyring, parse_cost_keyring


class Settings(BaseSettings):
    app_name: str = "Marko API"
    build_identity: str = "NOT_AVAILABLE"
    environment: str = "development"
    debug: bool = False
    api_prefix: str = "/api/v1"
    database_url: str = "postgresql+asyncpg://marko@localhost:5432/marko"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    celery_visibility_timeout_seconds: int = Field(default=3600, gt=0)
    api_docs_enabled: bool | None = None
    allowed_hosts: str = "localhost,127.0.0.1,test,testserver"
    cors_origins: str = "http://localhost:8080,http://localhost:3000"
    cors_allow_credentials: bool = False
    cors_methods: str = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
    cors_headers: str = "Authorization,Content-Type,Accept,Origin,X-Request-ID"
    firebase_project_id: str = ""
    prom_marketplace_source_access_verdict: Literal[
        "PERMITTED_OFFICIAL",
        "PERMITTED_LIMITED",
        "NOT_PERMITTED",
        "UNKNOWN",
    ] = "NOT_PERMITTED"
    prom_marketplace_source_access_reference: str = ""
    cost_privacy_mode: Literal[
        "UNDECIDED",
        "LOCAL_DEVICE_ONLY",
        "SERVER_SIDE_ENCRYPTED",
    ] = "UNDECIDED"
    cost_encryption_active_key_id: str = ""
    cost_encryption_keys_json: SecretStr = SecretStr("")
    pricing_collection_min_interval_seconds: float = 2.0
    pricing_circuit_failure_threshold: int = 5
    pricing_circuit_open_seconds: int = 300
    pricing_dispatch_batch_size: int = 100
    pricing_oe_reenrichment_batch_size: int = Field(default=100, ge=1, le=1000)
    pricing_parser_schema_changed_alert_count: int = Field(default=0, ge=0)
    pricing_parser_schema_changed_critical_rate: Decimal = Field(
        default=Decimal("0.01"), ge=0, le=1
    )
    pricing_offer_internal_failure_alert_count: int = Field(default=0, ge=0)
    pricing_evidence_accounting_error_critical_count: int = Field(default=0, ge=0)
    pricing_verified_oe_drop_warning_delta: Decimal = Field(
        default=Decimal("0.20"), ge=0, le=1
    )
    pricing_source_confidence_p50_drop_warning_delta: Decimal = Field(
        default=Decimal("0.15"), ge=0, le=1
    )
    pricing_collection_worker_count: int = 1
    pricing_collection_max_task_executions: int = 4
    pricing_collection_item_deadline_seconds: int = 1800
    pricing_collection_lease_seconds: int = 900
    # The collection task hosts ``ensure_run_item_comparability_reviews``, so in
    # ``shadow``/``required`` mode its budget is scraping *plus* up to
    # ``pricing_llm_max_provider_calls_per_position`` provider calls of up to
    # ``pricing_llm_timeout_seconds`` each -- 1800 s of reviews alone against
    # the former 840 s limit.  The two numbers were inconsistent by
    # construction: a position with a wide cohort could only end in
    # SoftTimeLimitExceeded and a retry, re-scraping and re-billing on the way.
    pricing_collection_task_soft_time_limit_seconds: int = 2700
    pricing_collection_task_time_limit_seconds: int = 2820
    # One no-OE item is discovery plus enrichment of every search candidate plus
    # up to ``pricing_no_oe_max_provider_calls`` reviews.  Measured 2026-08-14:
    # enrichment alone ran past 600 s on a 195-candidate search, and ten xhigh
    # reviews add ~700 s on top, so the former hardcoded 600/660 could not hold
    # a successful item -- it always raised SoftTimeLimitExceeded and retried.
    no_oe_discovery_task_soft_time_limit_seconds: int = 2700
    no_oe_discovery_task_time_limit_seconds: int = 2820
    pricing_scraper_http_timeout_seconds: float = 30.0
    pricing_scraper_http_max_attempts: int = 4
    pricing_scraper_request_delay_seconds: float = 1.0
    pricing_scraper_request_jitter_seconds: float = 0.5
    #: Raised from 3 to match catalog discovery: the two paths were reading
    #: different amounts of the same result set, and the pricing side had
    #: no instrumentation saying what its lower cap cost.
    pricing_scraper_max_search_pages: int = Field(default=10, ge=1, le=50)
    #: Pages of prom.ua's own part-code listing to walk.  Thirty offers per
    #: page, and a grouping can hold hundreds, so this cap discards market
    #: rather than noise; it is deliberately not the search cap.
    pricing_scraper_max_oe_page_pages: int = Field(default=4, ge=1, le=20)
    pricing_scraper_max_sellers: int = 10
    #: Candidate cards to fetch per position; ``0`` means every external row.
    #: Owner decision 2026-08-06: parse as many as possible, so the gates pick
    #: among all of them instead of trusting the pre-fetch title ranking. This
    #: is affordable only because retained card bytes are replayed across
    #: positions and runs; see ``pricing_detail_replay_max_age_hours``.
    pricing_scraper_max_detail_cards: int = Field(default=0, ge=0, le=500)
    #: How long a retained product card may be replayed instead of refetched.
    #: A card supplies no monetary field — price, availability, title, images
    #: and seller identity all stay at listing time — so staleness here cannot
    #: move a price. ``0`` disables the shared cache.
    pricing_detail_replay_max_age_hours: int = Field(default=72, ge=0, le=720)
    #: Distinct external sellers a position must reach before a declared
    #: cross number is spent on it. One seller is not a market, and a
    #: recommendation wants several independent ones.
    pricing_scraper_min_independent_sellers: int = Field(default=3, ge=0, le=50)
    catalog_discovery_max_search_pages: int = Field(default=10, ge=1, le=50)
    pricing_brand_tiers_path: str = ""
    pricing_crosses_path: str = "config/crosses.yaml"
    pricing_candidate_selection_path: str = "config/comparability.yaml"
    catalog_characteristics_path: str = "config/catalog_characteristics.yaml"
    pricing_raise_policy_path: str = "config/raise_policy.yaml"
    pricing_v3_robust_dispersion_enabled: bool = False
    pricing_v3_activation_artifact: str = ""
    pricing_v3_activation_sha256: str = ""
    pricing_comparability_v1_automatic_enabled: bool = False
    pricing_comparability_activation_artifact: str = ""
    pricing_comparability_activation_sha256: str = ""
    pricing_llm_comparability_mode: Literal["off", "shadow", "required"] = "off"
    pricing_llm_provider: Literal["openai_responses", "codex_cli"] = "openai_responses"
    pricing_llm_codex_bin: str = "codex"
    pricing_no_oe_discovery_enabled: bool = False
    pricing_no_oe_max_items: int = Field(default=20, ge=1, le=80)
    pricing_no_oe_max_provider_calls: int = Field(default=10, ge=1, le=20)
    # Кнопка «Сопоставить» в карточке: платный отсев спарсенных объявлений.
    # Собственный выключатель, а не общий с дорожкой без OE — та закрыта по
    # своей причине (инцидент 21.08) и висит на другой точке входа. Fail-closed:
    # пока не включено явно, операторская кнопка ничего не тратит.
    catalog_match_enabled: bool = False
    # Верхняя граница на одно нажатие. Карточка 2141006 даёт 42 группы; предел
    # существует, чтобы аномальная выдача не превратила один клик в сотни
    # вызовов, а не чтобы обрезать нормальную работу.
    catalog_match_max_groups: int = Field(default=80, ge=1, le=200)
    pricing_llm_base_url: str = "https://api.openai.com/v1"
    pricing_llm_api_key: SecretStr = SecretStr("")
    pricing_llm_model: str = "gpt-5.6-luna"
    # The paid comparator stays off by default.  Whenever an acceptance or
    # advisory run enables it, the run manifest pins this value so cached
    # evidence from a cheaper effort cannot be reused as xhigh evidence (or
    # vice versa).
    pricing_llm_reasoning_effort: Literal[
        "none", "low", "medium", "high", "xhigh", "max"
    ] = "xhigh"
    pricing_llm_image_detail: Literal["auto", "low", "high"] = "auto"
    pricing_llm_rate_version: str = "openai-gpt-5.6-luna-standard-2026-07-30"
    # Measured 2026-08-14 against gpt-5.6-luna at xhigh, on one realistic no-OE
    # review (2.6k chars of input): 71 s wall clock and 9 008 output tokens, of
    # which 6 214 were reasoning.  Reasoning is billed inside
    # ``max_output_tokens``, so the previous 1 600 budget spent the entire
    # allowance before the verdict began: the provider answered ``incomplete``
    # with an empty output on every call, which the adapter turns into
    # ``LLM_RESPONSE_INCOMPLETE``.  Paid for, and unusable.  The previous 60 s
    # timeout expired before that same call returned, and the adapter retries
    # once, so each review was billed twice and still produced nothing.
    #
    # 16 000 then proved short for the OEM lane, whose payload is 12 647 input
    # tokens against the 3 118 that measurement used, and one review of the
    # first ``required`` run still came back ``incomplete``.  These two move
    # together or not at all: that same measurement is 127 output tokens per
    # second, so a 24 000-token answer needs about 189 s and a 180 s timeout
    # would kill it just before it lands -- and then post again, and bill
    # twice, which is the failure this comment already describes once.  240 s
    # is also the ceiling the schedule allows: the no-OE task grants
    # ``pricing_no_oe_max_provider_calls`` reviews inside one soft limit, and
    # 10 x 240 s = 2 400 s still fits under 2 700 s where 300 s would not.
    pricing_llm_timeout_seconds: float = Field(default=240.0, gt=0, le=300)
    pricing_llm_max_output_tokens: int = Field(default=24000, ge=256, le=32000)
    pricing_llm_max_images: int = Field(default=4, ge=0, le=10)
    pricing_llm_max_concurrency: int = Field(default=4, ge=1, le=32)
    # Retained for deployment compatibility with existing manifests.  The v2
    # walk no longer stops after N positive reviews: every persisted candidate
    # receives a terminal review or an explicit budget-exhausted manual state.
    pricing_llm_max_confirmed_reviews: int = Field(default=10, ge=1, le=200)
    # Hard bound on provider calls spent on ONE catalogue position, applied in
    # every mode.  The confirmation ceiling above bounds nothing in ``required``
    # mode, where it is deliberately raised to the cohort size, and it bounds
    # nothing in any mode when the cohort confirms nothing -- it counts
    # confirmations, not calls.  Cohort width is not a bound either: acquisition
    # is page-capped rather than seller-capped, so a part-code page keeps a
    # median 81 offers past the gates.  This is the only number that caps the
    # bill.
    #
    # Exhausting it is fail-closed and explicit, never a silent downgrade of
    # ``required`` to ``shadow``: the offers it declines carry an
    # ``INSUFFICIENT_DATA`` decision stamped
    # ``LLM_PROVIDER_CALL_BUDGET_EXHAUSTED``, which ``engine.py`` turns into
    # ``MANUAL_LLM_COMPARABILITY_INSUFFICIENT`` and routes to manual review.
    # They are decisions on the record, so the finalizer barrier still clears.
    #
    # The default equals ``pricing_scraper_max_sellers``, the cap the collector
    # already applies, so it changes nothing until that cap is raised: at ~46k
    # provider calls per catalogue today, an unbounded ``required`` mode over
    # 81-offer cohorts would cost ~376k.
    pricing_llm_max_provider_calls_per_position: int = Field(
        default=10,
        ge=1,
        le=200,
    )
    # --- AI-assisted evidence extraction (round 6) --------------------------
    #
    # ``off`` by default and there is no ``required`` value: this path reads a
    # capture and proposes what it says, it does not decide a price, so the only
    # useful second state is one where its output is recorded and compared
    # against the deterministic verifier without anything downstream consuming
    # it.  Adding ``required`` before that comparison exists would let an
    # unmeasured extractor gate the pipeline.
    pricing_ai_evidence_mode: Literal["off", "shadow"] = "off"
    pricing_ai_evidence_api_key: SecretStr = SecretStr("")
    pricing_ai_evidence_model: str = "gpt-5.6-luna"
    # ``medium`` deliberately, and it is not to be raised as a default.  Effort
    # is billed, the ceiling here is per candidate per position, and nothing has
    # yet shown that a higher setting extracts facts a strict schema plus the
    # deterministic verifier would not have caught anyway.  A deployment that
    # wants more sets it explicitly and owns the bill.
    pricing_ai_evidence_reasoning_effort: Literal[
        "none", "low", "medium", "high", "xhigh", "max"
    ] = "medium"
    pricing_ai_evidence_max_output_tokens: int = Field(default=1200, ge=256, le=4000)
    # The retained capture text handed to the model.  Bounds the input bill and,
    # with it, the blast radius of a capture that turned out to be a whole page
    # of markup rather than an offer.
    pricing_ai_evidence_max_input_chars: int = Field(default=20_000, ge=500, le=200_000)
    pricing_ai_evidence_max_calls_per_position: int = Field(default=4, ge=1, le=200)
    pricing_ai_evidence_max_candidates_per_position: int = Field(
        default=4, ge=1, le=200
    )
    pricing_ai_evidence_max_concurrency: int = Field(default=2, ge=1, le=32)
    # Escalation is a second, dearer call for the candidates the first pass
    # could not resolve.  Off by default and inert unless a model *and* an
    # effort are both named, so a half-configured escalation cannot quietly
    # inherit the cheap model's settings and double the bill for nothing.
    pricing_ai_evidence_escalation_enabled: bool = False
    pricing_ai_evidence_escalation_model: str = ""
    pricing_ai_evidence_escalation_reasoning_effort: (
        Literal["none", "low", "medium", "high", "xhigh", "max"] | None
    ) = None
    # Fitment is a later phase and is not part of the 2026-07-30 delivery, whose
    # scope the customer set as raise/cut against the cheapest comparable offer.
    # Its endpoints are implemented and tested but unreachable from the UI, so
    # publishing them would offer a feature nobody can use and nobody reviewed
    # for handover.  Off by default; a deployment opts in deliberately.
    fitment_api_enabled: bool = False
    operational_metrics_token: SecretStr = SecretStr("")
    e2e_auth_bypass: bool = False
    e2e_auth_token: str = ""
    e2e_task_hold_seconds: float = 0.0
    public_api_base_url: str = ""
    firebase_api_key: str = ""
    firebase_auth_domain: str = ""
    firebase_messaging_sender_id: str = ""
    firebase_web_app_id: str = ""
    store_sync_worker_count: int = 2

    store_sync_max_task_executions: int = 3
    store_sync_item_deadline_seconds: int = 3600
    store_sync_lease_seconds: int = 300
    store_sync_task_soft_time_limit_seconds: int = 1740
    store_sync_task_time_limit_seconds: int = 1800
    store_sync_retry_base_delay_seconds: int = 30
    store_sync_scraper_http_timeout_seconds: float = 30.0
    store_sync_scraper_http_max_attempts: int = 4
    store_sync_scraper_pages_per_task: int = Field(default=5, ge=1, le=100)
    store_sync_persistence_batch_size: int = Field(default=250, ge=25, le=2000)
    store_sync_scraper_total_page_limit: int = Field(
        default=1000,
        ge=1,
        le=10_000,
    )
    store_sync_scraper_max_pages: int = 0
    store_monitoring_enabled: bool = True
    # Решение заказчика, передано владельцем 2026-08-21: прогоны проверки цен
    # не должны стартовать сами — ни после импорта XLSX, ни после
    # синхронизации магазина. False глушит оба автозапуска в
    # services/attention.py; ручной запуск оператором не затрагивается.
    attention_monitoring_enabled: bool = True
    store_monitoring_refresh_interval_seconds: int = Field(
        default=3600,
        ge=300,
        le=86_400,
    )
    store_monitoring_scan_interval_seconds: int = Field(
        default=300,
        ge=60,
        le=3600,
    )
    store_monitoring_batch_size: int = Field(default=10, ge=1, le=100)
    store_url_resolver_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    store_url_resolver_max_redirects: int = Field(default=3, ge=0, le=10)
    store_url_resolver_max_response_bytes: int = Field(
        default=2 * 1024 * 1024,
        ge=64 * 1024,
        le=10 * 1024 * 1024,
    )
    scrape_raw_evidence_replay_enabled: bool = True
    scrape_evidence_gc_batch_size: int = 1000
    scrape_evidence_gc_interval_seconds: int = 3600
    scrape_outbox_reconcile_batch_size: int = 100
    scrape_outbox_reconcile_interval_seconds: int = 15
    workflow_reconcile_batch_size: int = Field(default=100, ge=1, le=1000)
    workflow_reconcile_interval_seconds: int = Field(
        default=60,
        ge=15,
        le=3600,
    )
    workflow_stale_after_seconds: int = Field(
        default=3600,
        ge=300,
        le=86_400,
    )
    scheduler_singleton_lock_key: str = "marko:scheduler:singleton:v1"
    scheduler_singleton_ttl_seconds: int = Field(default=90, ge=30, le=600)
    scheduler_singleton_refresh_seconds: int = Field(default=20, ge=1, le=120)
    scheduler_singleton_reacquire_initial_seconds: float = Field(
        default=1.0, ge=0.1, le=60
    )
    scheduler_singleton_reacquire_max_seconds: float = Field(
        default=30.0, ge=0.1, le=300
    )
    scheduler_health_state_path: str = "/tmp/marko-scheduler-health.json"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("pricing_ai_evidence_escalation_reasoning_effort", mode="before")
    @classmethod
    def _empty_ai_evidence_escalation_effort_is_unconfigured(
        cls, value: object
    ) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value

    @model_validator(mode="after")
    def validate_security_boundary(self) -> Settings:
        environment = self.environment.strip().casefold()
        if not environment:
            raise ValueError("ENVIRONMENT must not be empty")
        if self.cors_allow_credentials and "*" in self.cors_origin_list:
            raise ValueError("Wildcard CORS origins cannot be used with credentials")
        if self.prom_marketplace_source_access_verdict.startswith("PERMITTED_"):
            if not self.prom_marketplace_source_access_reference.strip():
                raise ValueError(
                    "A permitted Prom marketplace source requires an auditable "
                    "PROM_MARKETPLACE_SOURCE_ACCESS_REFERENCE"
                )
        metrics_token = self.operational_metrics_token.get_secret_value()
        if metrics_token and len(metrics_token) < 32:
            raise ValueError(
                "OPERATIONAL_METRICS_TOKEN must contain at least 32 characters"
            )
        if self.e2e_auth_bypass:
            if environment != "e2e":
                raise ValueError("E2E_AUTH_BYPASS is allowed only in ENVIRONMENT=e2e")
            if len(self.e2e_auth_token) < 32:
                raise ValueError(
                    "E2E_AUTH_TOKEN must contain at least 32 characters when bypass is enabled"
                )
        elif self.e2e_auth_token:
            raise ValueError("E2E_AUTH_TOKEN requires E2E_AUTH_BYPASS=true")
        if self.e2e_task_hold_seconds < 0:
            raise ValueError("E2E_TASK_HOLD_SECONDS must not be negative")
        if self.e2e_task_hold_seconds and environment != "e2e":
            raise ValueError("E2E_TASK_HOLD_SECONDS is allowed only in ENVIRONMENT=e2e")
        if self.scheduler_singleton_refresh_seconds * 2 >= (
            self.scheduler_singleton_ttl_seconds
        ):
            raise ValueError(
                "SCHEDULER_SINGLETON_REFRESH_SECONDS must be less than half "
                "SCHEDULER_SINGLETON_TTL_SECONDS"
            )
        if (
            self.scheduler_singleton_reacquire_max_seconds
            < self.scheduler_singleton_reacquire_initial_seconds
        ):
            raise ValueError(
                "SCHEDULER_SINGLETON_REACQUIRE_MAX_SECONDS must not be less than "
                "SCHEDULER_SINGLETON_REACQUIRE_INITIAL_SECONDS"
            )
        if self.pricing_llm_comparability_mode != "off":
            if (
                self.pricing_llm_provider == "openai_responses"
                and not self.pricing_llm_api_key.get_secret_value().strip()
            ):
                raise ValueError(
                    "PRICING_LLM_API_KEY is required when "
                    "PRICING_LLM_COMPARABILITY_MODE is shadow or required"
                )
            if not self.pricing_llm_model.strip():
                raise ValueError(
                    "PRICING_LLM_MODEL is required when "
                    "PRICING_LLM_COMPARABILITY_MODE is shadow or required"
                )
            if not self.pricing_llm_rate_version.strip():
                raise ValueError(
                    "PRICING_LLM_RATE_VERSION is required when "
                    "PRICING_LLM_COMPARABILITY_MODE is shadow or required"
                )
            self._require_transport_base_url(environment)
        if self.pricing_llm_provider == "codex_cli":
            if environment not in {"development", "test", "e2e"}:
                raise ValueError("PRICING_LLM_PROVIDER=codex_cli is local/test only")
            if not self.pricing_llm_codex_bin.strip():
                raise ValueError("PRICING_LLM_CODEX_BIN must not be empty")
        if self.pricing_no_oe_discovery_enabled:
            if self.pricing_llm_model.strip() != "gpt-5.6-luna":
                raise ValueError("no-OE discovery requires gpt-5.6-luna")
            if self.pricing_llm_reasoning_effort != "xhigh":
                raise ValueError("no-OE discovery requires xhigh reasoning")
            # The effort this contour pins is billed inside the output budget,
            # and it is spent before the verdict starts.  Below these floors the
            # run does not degrade gracefully: every review is paid for, returns
            # ``incomplete`` or times out, and records no verdict.  Refuse to
            # boot instead, because the failure is invisible in the run itself.
            if self.pricing_llm_max_output_tokens < 12_000:
                raise ValueError(
                    "no-OE discovery requires PRICING_LLM_MAX_OUTPUT_TOKENS "
                    ">= 12000; xhigh reasoning alone spends about 6200 of them "
                    "before the verdict begins"
                )
            if self.pricing_llm_timeout_seconds < 120:
                raise ValueError(
                    "no-OE discovery requires PRICING_LLM_TIMEOUT_SECONDS "
                    ">= 120; one xhigh review measured 71 s"
                )
            if (
                self.pricing_llm_provider == "openai_responses"
                and not self.pricing_llm_api_key.get_secret_value().strip()
            ):
                raise ValueError(
                    "PRICING_LLM_API_KEY is required for no-OE Responses API"
                )
        if self.pricing_ai_evidence_mode != "off":
            # Deliberately no API-key requirement, and this is the whole
            # contract: a missing key must produce a typed ``UNCONFIGURED``
            # extraction row with no HTTP request, not a process that refuses to
            # boot.  Raising here would make an off-by-default, shadow-only
            # feature able to take the API down on a deployment that merely
            # flipped the mode -- and it would move the failure from a row an
            # operator can read to a crash loop.
            if not self.pricing_ai_evidence_model.strip():
                raise ValueError(
                    "PRICING_AI_EVIDENCE_MODEL is required when "
                    "PRICING_AI_EVIDENCE_MODE is shadow"
                )
            if not is_immutable_model_snapshot(self.pricing_ai_evidence_model):
                raise ValueError(
                    "PRICING_AI_EVIDENCE_MODEL must be an immutable, bounded ASCII "
                    "snapshot id documented by the provider or ending in YYYY-MM-DD "
                    "when mode is shadow"
                )
            self._require_transport_base_url(environment)
        if self.pricing_ai_evidence_escalation_enabled:
            if self.pricing_ai_evidence_mode == "off":
                raise ValueError(
                    "PRICING_AI_EVIDENCE_ESCALATION_ENABLED requires "
                    "PRICING_AI_EVIDENCE_MODE to be shadow"
                )
            if not self.pricing_ai_evidence_escalation_model.strip():
                raise ValueError(
                    "PRICING_AI_EVIDENCE_ESCALATION_MODEL is required when "
                    "escalation is enabled"
                )
            if not is_immutable_model_snapshot(
                self.pricing_ai_evidence_escalation_model
            ):
                raise ValueError(
                    "PRICING_AI_EVIDENCE_ESCALATION_MODEL must be an immutable, "
                    "bounded ASCII snapshot id documented by the provider or ending "
                    "in YYYY-MM-DD"
                )
            if self.pricing_ai_evidence_escalation_reasoning_effort is None:
                raise ValueError(
                    "PRICING_AI_EVIDENCE_ESCALATION_REASONING_EFFORT is required "
                    "when escalation is enabled"
                )
        concurrent_collectors = max(
            1,
            self.store_sync_worker_count + self.pricing_collection_worker_count,
        )
        conservative_global_wait = self.pricing_collection_min_interval_seconds * max(
            0, concurrent_collectors - 1
        )
        attempts = max(1, self.store_sync_scraper_http_max_attempts)
        request_upper_bound = (
            attempts
            * (
                self.store_sync_scraper_http_timeout_seconds
                + self.pricing_scraper_request_delay_seconds
                + self.pricing_scraper_request_jitter_seconds
                + conservative_global_wait
            )
            + max(0, attempts - 1) * 60
        )
        chunk_upper_bound = (
            self.store_sync_scraper_pages_per_task * request_upper_bound + 120
        )
        if chunk_upper_bound >= self.store_sync_task_soft_time_limit_seconds:
            raise ValueError(
                "STORE_SYNC_SCRAPER_PAGES_PER_TASK exceeds the conservative "
                "store-sync soft-time-limit budget"
            )
        if not Path(self.scheduler_health_state_path).is_absolute():
            raise ValueError("SCHEDULER_HEALTH_STATE_PATH must be absolute")
        if self.cost_privacy_mode == "SERVER_SIDE_ENCRYPTED":
            parse_cost_keyring(
                active_key_id=self.cost_encryption_active_key_id,
                keys_json=self.cost_encryption_keys_json.get_secret_value(),
            )
        if environment == "production":
            if self.debug:
                raise ValueError("DEBUG must be false in production")
            if not self.allowed_host_list or "*" in self.allowed_host_list:
                raise ValueError(
                    "Production ALLOWED_HOSTS must be explicit and non-empty"
                )
            if "*" in self.cors_origin_list:
                raise ValueError("Production CORS_ORIGINS must not contain a wildcard")
            if not self.firebase_project_id.strip():
                raise ValueError("FIREBASE_PROJECT_ID must be configured in production")
            if self.pricing_v3_robust_dispersion_enabled and not all(
                (
                    self.pricing_v3_activation_artifact.strip(),
                    self.pricing_v3_activation_sha256.strip(),
                )
            ):
                raise ValueError(
                    "Robust v3 production activation requires an artifact and SHA-256"
                )
            if self.pricing_comparability_v1_automatic_enabled and not all(
                (
                    self.pricing_comparability_activation_artifact.strip(),
                    self.pricing_comparability_activation_sha256.strip(),
                )
            ):
                raise ValueError(
                    "Comparability automatic activation requires an artifact and SHA-256"
                )
        return self

    def _require_transport_base_url(self, environment: str) -> None:
        """One HTTPS rule for every consumer of the shared LLM transport.

        Comparability and evidence extraction post to the same base URL with the
        same credential, so the rule has to be stated once: two copies drift,
        and the copy that drifts is the one nobody looked at.
        """

        llm_base_url = self.pricing_llm_base_url.strip().casefold()
        if not (
            llm_base_url.startswith("https://")
            or (
                environment in {"development", "test", "e2e"}
                and llm_base_url.startswith("http://")
            )
        ):
            raise ValueError(
                "PRICING_LLM_BASE_URL must use HTTPS outside local/test environments"
            )

    @property
    def is_production(self) -> bool:
        return self.environment.strip().casefold() == "production"

    @property
    def ai_evidence_extraction_enabled(self) -> bool:
        return self.pricing_ai_evidence_mode != "off"

    @property
    def ai_evidence_api_key_configured(self) -> bool:
        """Whether a credential exists at all -- never the credential itself.

        The extraction service asks this instead of reaching for the secret, so
        the "is it configured" decision cannot accidentally be made by
        formatting the key into a log line or an error message.  ``SecretStr``
        already redacts ``repr``; this keeps the value from being touched in the
        first place.
        """

        return bool(
            self.pricing_ai_evidence_api_key.get_secret_value().strip()
            or self.pricing_llm_api_key.get_secret_value().strip()
        )

    @property
    def ai_evidence_escalation_configured(self) -> bool:
        return (
            self.pricing_ai_evidence_escalation_enabled
            and bool(self.pricing_ai_evidence_escalation_model.strip())
            and self.pricing_ai_evidence_escalation_reasoning_effort is not None
        )

    @property
    def effective_api_docs_enabled(self) -> bool:
        if self.api_docs_enabled is not None:
            return self.api_docs_enabled
        return not self.is_production

    @cached_property
    def cost_keyring(self) -> CostKeyring:
        if self.cost_privacy_mode != "SERVER_SIDE_ENCRYPTED":
            raise ValueError("Server-side cost encryption is not enabled")
        return parse_cost_keyring(
            active_key_id=self.cost_encryption_active_key_id,
            keys_json=self.cost_encryption_keys_json.get_secret_value(),
        )

    @property
    def allowed_host_list(self) -> list[str]:
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]

    @property
    def cors_method_list(self) -> list[str]:
        return [
            method.strip() for method in self.cors_methods.split(",") if method.strip()
        ]

    @property
    def cors_header_list(self) -> list[str]:
        return [
            header.strip() for header in self.cors_headers.split(",") if header.strip()
        ]

    @property
    def firebase_auth_issuer(self) -> str:
        return f"https://securetoken.google.com/{self.firebase_project_id}"

    @property
    def firebase_jwks_url(self) -> str:
        return (
            "https://www.googleapis.com/service_accounts/v1/jwk/"
            "securetoken@system.gserviceaccount.com"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def backend_config_path(raw_path: str) -> Path:
    """Resolve a configured path against the backend root when it is relative.

    ``catalog_discovery.resolve_backend_path`` does the same for the pricing
    configs; this copy exists so the importer does not have to import a module
    that pulls in the whole scraping stack to read one YAML file.
    """

    path = Path(raw_path).expanduser()
    if path.is_file():
        return path
    if not path.is_absolute():
        candidate = Path(__file__).resolve().parents[3] / path
        if candidate.is_file():
            return candidate
    return path
