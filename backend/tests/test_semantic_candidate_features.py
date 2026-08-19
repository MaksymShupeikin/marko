from __future__ import annotations

import re
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from marko.services.llm_comparability import (
    ComparabilityMatchLevel,
    FindingOutcome,
    IdentityVerdict,
    ImageConsistency,
    LLMComparabilityOutput,
    PricingAdmission,
    ReviewDimensionFinding,
    _PreparedReview,
    _effective_identity_match_level,
    _hard_stop_output,
    derive_pricing_admission,
    deterministic_hard_stop_conflicts,
)
from marko.services.market_collection import _availability
from marko.services.semantic_candidate_features import (
    SEMANTIC_FEATURE_EXTRACTOR_VERSION,
    _PART_PATTERNS,
    build_semantic_feature_matrix,
    extract_semantic_features,
)


def _matrix(ours: str, candidate: str, **candidate_fields: object) -> dict:
    return build_semantic_feature_matrix(
        {"name": ours},
        {"title": candidate, **candidate_fields},
    )


def test_live_brake_line_cannot_be_priced_as_a_flexible_brake_hose() -> None:
    matrix = _matrix(
        "Шланг тормозной передний VW Transporter T4 90-03",
        "Гальмівна трубка FEBI 34368 Volkswagen Transporter 7D0611702",
    )

    assert matrix["comparisons"]["part_type"]["state"] == "MATCH"
    assert matrix["comparisons"]["part_subtype"] == {
        "state": "CONFLICT",
        "our_values": ["brake_hose"],
        "candidate_values": ["brake_line"],
    }
    assert {row["dimension"] for row in matrix["hard_stop_conflicts"]} == {
        "part_subtype"
    }


@pytest.mark.parametrize(
    "title",
    [
        "Тормозная трубка VW Transporter",
        "Трубка гальмівна VW Transporter",
        "Brake pipe VW Transporter",
    ],
)
def test_brake_line_wording_is_extracted_without_guessing_from_the_number(
    title: str,
) -> None:
    features = extract_semantic_features({"name": title})

    assert features["part_family"].values == ("brake_hydraulics",)
    assert features["part_subtype"].values == ("brake_line",)


def test_plural_steering_end_wording_keeps_the_live_candidate_typed() -> None:
    matrix = _matrix(
        "Наконечник рулевой тяги VW Polo Lupo правый",
        "Кермові наконечники ASMETAL Volkswagen Polo Seat Ibiza",
    )

    assert matrix["comparisons"]["part_type"]["state"] == "MATCH"
    assert matrix["comparisons"]["part_subtype"]["state"] == "MATCH"
    assert not matrix["hard_stop_conflicts"]


def test_seed_asserted_commercial_dimensions_are_required_for_cross_pricing() -> None:
    matrix = _matrix(
        "Наконечник рулевой тяги передний правый VW Polo",
        "Наконечник рулевой тяги VW Polo",
    )

    assert matrix["hard_stop_conflicts"] == []
    assert {
        "part_type",
        "part_subtype",
        "assembly_level",
        "side",
        "position",
    }.issubset(matrix["analogue_required_dimensions"])
    assert matrix["comparisons"]["side"]["state"] == "UNKNOWN"
    assert matrix["comparisons"]["position"]["state"] == "UNKNOWN"


def test_inner_and_outer_cv_joints_are_different_sellable_variants() -> None:
    inner = extract_semantic_features({"name": "Шрус внутренний VW Polo 25307"})
    outer = extract_semantic_features({"name": "Шрус наружный VW Polo 25307"})
    assert inner["cv_joint_variant"].values == ("inner",)
    assert outer["cv_joint_variant"].values == ("outer",)

    matrix = _matrix(
        "Шрус внутренний VW Polo 25307",
        "Шрус наружный VW Polo 25307",
    )
    conflict = next(
        item
        for item in matrix["hard_stop_conflicts"]
        if item["dimension"] == "cv_joint_variant"
    )
    assert conflict["our_value"] == "inner"
    assert conflict["candidate_value"] == "outer"
    hard_stop = _hard_stop_output(matrix["hard_stop_conflicts"])
    assert hard_stop.identity_verdict is IdentityVerdict.NOT_MATCH
    assert "DETERMINISTIC_CONFLICT_CV_JOINT_VARIANT" in hard_stop.reason_codes

    same = _matrix(
        "Шрус внутренний VW Polo 25307",
        "Внутренний CV joint VW Polo 25307",
    )
    assert same["comparisons"]["cv_joint_variant"]["state"] == "MATCH"


def test_inner_word_on_an_unrelated_part_does_not_create_cv_variant() -> None:
    features = extract_semantic_features(
        {"name": "Внутренний подшипник ступицы VW Polo"}
    )
    assert features["cv_joint_variant"].values == ()


def test_explicit_fuel_type_mismatch_is_a_identity_hard_stop() -> None:
    diesel = extract_semantic_features({"name": "Форсунка дизельная Ford Transit 2.0"})
    petrol = extract_semantic_features({"name": "Форсунка бензиновая Ford Transit 2.0"})
    assert diesel["fuel_type"].values == ("diesel",)
    assert petrol["fuel_type"].values == ("petrol",)

    matrix = _matrix(
        "Форсунка дизельная Ford Transit 2.0",
        "Форсунка бензиновая Ford Transit 2.0",
    )
    assert matrix["comparisons"]["fuel_type"]["state"] == "CONFLICT"
    conflict = next(
        item
        for item in matrix["hard_stop_conflicts"]
        if item["dimension"] == "fuel_type"
    )
    assert conflict["our_value"] == "diesel"
    assert conflict["candidate_value"] == "petrol"
    output = _hard_stop_output(matrix["hard_stop_conflicts"])
    assert output.identity_verdict is IdentityVerdict.NOT_MATCH
    assert "DETERMINISTIC_CONFLICT_FUEL_TYPE" in output.reason_codes


def test_structured_fuel_type_is_used_without_guessing_missing_text() -> None:
    features = extract_semantic_features(
        {"name": "Форсунка Ford Transit", "fuelType": "diesel"}
    )
    assert features["fuel_type"].values == ("diesel",)
    assert (
        extract_semantic_features({"name": "Форсунка Ford Transit"})["fuel_type"].values
        == ()
    )


def test_upper_and_lower_ball_joint_are_different_sellable_variants() -> None:
    lower = extract_semantic_features({"name": "Шаровая опора нижняя VW Golf"})
    upper = extract_semantic_features({"name": "Шаровая опора верхняя VW Golf"})
    assert lower["vertical_position"].values == ("lower",)
    assert upper["vertical_position"].values == ("upper",)

    matrix = _matrix(
        "Шаровая опора нижняя VW Golf",
        "Шаровая опора верхняя VW Golf",
    )
    assert matrix["comparisons"]["vertical_position"]["state"] == "CONFLICT"
    assert "vertical_position" in {
        item["dimension"] for item in matrix["hard_stop_conflicts"]
    }


def test_brake_disc_diameter_in_title_is_compared() -> None:
    different = _matrix(
        "Диск тормозной передний VW Golf 256mm",
        "Диск тормозной передний VW Golf 280mm",
    )
    same = _matrix(
        "Диск тормозной передний VW Golf 256mm",
        "Диск тормозной передний VW Golf 256mm",
    )
    assert different["our_product"]["dimensions"]["values"] == ["256mm"]
    assert different["candidate"]["dimensions"]["values"] == ["280mm"]
    assert different["comparisons"]["technical_specs"]["state"] == "CONFLICT"
    assert "technical_specs" in {
        item["dimension"] for item in different["hard_stop_conflicts"]
    }
    assert same["comparisons"]["technical_specs"]["state"] == "MATCH"


def test_thermostat_housing_is_not_the_complete_thermostat() -> None:
    housing = extract_semantic_features({"name": "Корпус термостата Ford Focus 1.8"})
    complete = extract_semantic_features({"name": "Термостат Ford Focus 1.8"})
    with_housing = extract_semantic_features(
        {"name": "Термостат с корпусом Ford Focus 1.8"}
    )

    assert housing["part_subtype"].values == ("thermostat_housing",)
    assert housing["assembly_level"].values == ("housing",)
    assert complete["part_subtype"].values == ("coolant_thermostat",)
    assert with_housing["part_subtype"].values == ("thermostat_with_housing",)
    assert with_housing["assembly_level"].values == ("complete_assembly",)

    matrix = _matrix(
        "Термостат Ford Focus 1.8 1086282",
        "Корпус термостата Ford Focus 1.8 1086282",
    )
    assert {item["dimension"] for item in matrix["hard_stop_conflicts"]} >= {
        "part_subtype",
        "assembly_level",
    }


def test_power_steering_reservoir_cap_is_not_the_reservoir() -> None:
    reservoir = extract_semantic_features({"name": "Бачок ГУР VW Passat B3"})
    cap = extract_semantic_features({"name": "Кришка бачка ГПР VW Passat B3"})
    assert reservoir["part_subtype"].values == ("reservoir",)
    assert cap["part_subtype"].values == ("reservoir_cap",)
    assert cap["assembly_level"].values == ("component",)

    matrix = _matrix(
        "Бачок ГУР VW Passat B3",
        "Крышка бачка ГУР VW Passat B3",
    )
    assert {item["dimension"] for item in matrix["hard_stop_conflicts"]} >= {
        "part_subtype",
        "assembly_level",
    }


@pytest.mark.parametrize(
    ("seed", "component", "seed_subtype", "component_subtype"),
    (
        (
            "Радиатор охлаждения VW Golf",
            "Крышка радиатора VW Golf",
            "engine_cooling_radiator",
            "radiator_cap",
        ),
        (
            "Ступица колеса VW Golf",
            "Фланец ступицы VW Golf",
            "wheel_hub",
            "wheel_hub_flange",
        ),
        (
            "Генератор VW Golf",
            "Регулятор напряжения генератора VW Golf",
            "alternator_assembly",
            "alternator_regulator",
        ),
        (
            "Помпа водяная VW Golf",
            "Крыльчатка водяной помпы VW Golf",
            "water_pump",
            "water_pump_impeller",
        ),
        (
            "Компрессор кондиционера VW Golf",
            "Муфта компрессора кондиционера VW Golf",
            "ac_compressor",
            "compressor_clutch",
        ),
        (
            "Фильтр масляный VW Golf",
            "Корпус масляного фильтра VW Golf",
            "oil_filter",
            "oil_filter_housing",
        ),
        (
            "Ремень ГРМ VW Golf",
            "Комплект ремня ГРМ VW Golf",
            "timing_belt",
            "timing_belt_kit",
        ),
        (
            "Ролик натяжной ГРМ VW Golf",
            "Комплект роликов ГРМ VW Golf",
            "timing_roller",
            "timing_roller_kit",
        ),
        (
            "Датчик ABS VW Golf",
            "Кольцо ABS VW Golf",
            "abs_sensor",
            "abs_ring",
        ),
        (
            "Фара VW Golf",
            "Корпус фары VW Golf",
            "headlamp",
            "headlamp_housing",
        ),
        (
            "Ручка двери VW Golf",
            "Механизм ручки двери VW Golf",
            "door_handle",
            "door_handle_mechanism",
        ),
        (
            "Диск тормозной VW Golf",
            "Колодки тормозные VW Golf",
            "brake_disc",
            "brake_pad",
        ),
    ),
)
def test_v30_component_boundaries_block_false_cross_matches(
    seed: str,
    component: str,
    seed_subtype: str,
    component_subtype: str,
) -> None:
    seed_features = extract_semantic_features({"name": seed})
    component_features = extract_semantic_features({"name": component})
    assert seed_features["part_subtype"].values == (seed_subtype,)
    assert component_features["part_subtype"].values == (component_subtype,)

    matrix = _matrix(seed, component)
    assert matrix["hard_stop_conflicts"]
    assert {item["dimension"] for item in matrix["hard_stop_conflicts"]} >= {
        "part_subtype",
        "assembly_level",
    }


def test_v30_component_patterns_do_not_reclassify_complete_with_component_titles() -> None:
    complete_titles = (
        ("Радиатор с крышкой VW Golf", "engine_cooling_radiator"),
        ("Помпа водяная с крыльчаткой VW Golf", "water_pump"),
        ("Компрессор кондиционера с муфтой VW Golf", "ac_compressor"),
        ("Фара с корпусом VW Golf", "headlamp"),
        ("Ступица с фланцем VW Golf", "wheel_hub"),
        ("Генератор с регулятором VW Golf", "alternator_assembly"),
    )
    for title, expected_subtype in complete_titles:
        features = extract_semantic_features({"name": title})
        assert features["part_subtype"].values == (expected_subtype,), title


@pytest.mark.parametrize(
    ("seed", "kit_or_component", "seed_subtype", "candidate_subtype"),
    (
        (
            "Ступичный подшипник VW Golf",
            "Ступица в сборе VW Golf",
            "wheel_bearing",
            "wheel_hub",
        ),
        (
            "Форсунка VW Golf",
            "Ремкомплект форсунки VW Golf",
            "fuel_injector",
            "fuel_injector_repair_kit",
        ),
        (
            "Фильтр воздушный VW Golf",
            "Корпус воздушного фильтра VW Golf",
            "engine_air_filter",
            "engine_air_filter_housing",
        ),
        (
            "Опора двигателя VW Golf",
            "Кронштейн опоры двигателя VW Golf",
            "engine_or_transmission_mount",
            "engine_mount_bracket",
        ),
    ),
)
def test_v31_remaining_component_boundaries_block_false_cross_matches(
    seed: str,
    kit_or_component: str,
    seed_subtype: str,
    candidate_subtype: str,
) -> None:
    seed_features = extract_semantic_features({"name": seed})
    candidate_features = extract_semantic_features({"name": kit_or_component})
    assert seed_features["part_subtype"].values == (seed_subtype,)
    assert candidate_features["part_subtype"].values == (candidate_subtype,)

    matrix = _matrix(seed, kit_or_component)
    assert {item["dimension"] for item in matrix["hard_stop_conflicts"]} >= {
        "part_subtype",
        "assembly_level",
    }


@pytest.mark.parametrize(
    ("seed", "candidate", "expected_dimension"),
    (
        (
            "Стеклоподъемник VW T5 без мотора",
            "Стеклоподъемник VW T5 с мотором",
            "included_components",
        ),
        (
            "Колодки тормозные VW Golf без датчика износа",
            "Колодки тормозные VW Golf с датчиком износа",
            "included_components",
        ),
    ),
)
def test_v32_optional_component_variants_are_hard_stopped(
    seed: str,
    candidate: str,
    expected_dimension: str,
) -> None:
    matrix = _matrix(seed, candidate)

    assert matrix["comparisons"][expected_dimension]["state"] == "CONFLICT"
    assert expected_dimension in {
        item["dimension"] for item in matrix["hard_stop_conflicts"]
    }


def test_v32_optional_component_extraction_is_not_triggered_by_negative_substrings() -> None:
    assert extract_semantic_features(
        {"name": "Стеклоподъемник VW T5 без мотора"}
    )["included_components"].values == ("without_window_regulator_motor",)
    assert extract_semantic_features(
        {"name": "Колодки тормозные VW Golf без датчика"}
    )["included_components"].values == ("without_brake_wear_sensor",)


@pytest.mark.parametrize(
    ("seed", "candidate"),
    (
        (
            "Радиатор кондиционера Audi A6 без осушителя",
            "Радиатор кондиционера Audi A6 с осушителем",
        ),
        (
            "Рейка рулевая Sprinter без тяг",
            "Рейка рулевая Sprinter с тягами",
        ),
        (
            "Суппорт задний VW без скобы",
            "Суппорт задний VW с скобой",
        ),
    ),
)
def test_v33_explicit_package_variants_are_hard_stopped(
    seed: str,
    candidate: str,
) -> None:
    matrix = _matrix(seed, candidate)

    assert matrix["comparisons"]["included_components"]["state"] == "CONFLICT"
    assert "included_components" in {
        item["dimension"] for item in matrix["hard_stop_conflicts"]
    }


def test_exact_oe_does_not_bypass_explicit_fuel_conflict() -> None:
    matrix = _matrix(
        "Форсунка дизельная Ford Transit 2.0",
        "Форсунка бензиновая Ford Transit 2.0",
    )
    output = _hard_stop_output(matrix["hard_stop_conflicts"])
    admission = derive_pricing_admission(
        _prepared_with_matrix(
            matrix,
            oe_status="VERIFIED_EXACT",
            verified_cross=False,
        ),
        output,
    )

    assert output.identity_verdict is IdentityVerdict.NOT_MATCH
    assert admission.status is PricingAdmission.EXCLUDED
    assert admission.reason_codes == ("IDENTITY_NOT_MATCH",)


def test_badge_engineered_vehicle_make_is_not_a_universal_cross_requirement() -> None:
    matrix = _matrix(
        "Інтеркулер Mercedes Sprinter 717*255",
        "Інтеркулер Volkswagen LT35 717*255",
    )

    assert matrix["comparisons"]["vehicle_make"]["state"] == "CONFLICT"
    assert "vehicle_make" not in matrix["analogue_required_dimensions"]


def test_saved_five_pair_semantics_are_conservative_and_category_aware() -> None:
    radiator = _matrix(
        "Радіатор Iveco 625*440",
        "Радіатор охолодження двигуна Iveco Daily E2 2.8TDI (1996-1999) OE:93818439",
    )
    wrong_lock_component = _matrix(
        "Корпус замка зажигания VW Golf, Passat 88-96",
        "357905851D контактна група Vw Golf 3",
    )
    universal_lock = _matrix(
        "Замок зажигания универсальный (6pin) в сборе",
        "Замок запалювання універсальний (6 pin) у зборі",
    )
    reservoir = _matrix(
        "Бачок ГУР VW Passat B3/B4",
        "Бачок ГПР Passat B3/B4, JP Group (1145200500)",
    )
    thermostat = _matrix(
        "Термостат Ford Escort/Fiesta/Focus/Transit Connect 1.8-2.5 D",
        "Термостат FORD ESCORT/FIESTA/FOCUS/GALAXY/MONDEO/ORION/SIERRA/TRANSIT, CALORSTAT BY VERNET (TH652688J)",
    )

    assert radiator["extractor_version"] == SEMANTIC_FEATURE_EXTRACTOR_VERSION
    assert radiator["comparisons"]["part_type"]["state"] == "MATCH"
    assert radiator["comparisons"]["technical_specs"]["state"] == "UNKNOWN"
    assert radiator["analogue_required_dimensions"] == [
        "part_type",
        "technical_specs",
        "inlet_outlet",
        "engine",
        "part_subtype",
        "assembly_level",
        # Present since the marketplace-silence default (owner decision
        # 2026-08-19): our side always asserts a condition now, so an
        # analogue must match it.
        "condition",
    ]

    assert wrong_lock_component["comparisons"]["part_type"]["state"] == "MATCH"
    assert wrong_lock_component["comparisons"]["assembly_level"]["state"] == "CONFLICT"
    assert {
        row["dimension"] for row in wrong_lock_component["hard_stop_conflicts"]
    } == {"part_subtype", "assembly_level"}

    assert universal_lock["comparisons"]["assembly_level"]["state"] == "MATCH"
    assert universal_lock["comparisons"]["connectors_pins"]["state"] == "MATCH"
    assert not universal_lock["hard_stop_conflicts"]

    assert reservoir["comparisons"]["part_type"]["state"] == "MATCH"
    assert reservoir["comparisons"]["ports"]["state"] == "UNKNOWN"
    assert "ports" in reservoir["analogue_required_dimensions"]

    assert thermostat["comparisons"]["part_type"]["state"] == "MATCH"
    assert thermostat["comparisons"]["opening_temperature"]["state"] == "UNKNOWN"
    assert "opening_temperature" in thermostat["analogue_required_dimensions"]

    generic_lock = _matrix(
        "Корпус замка зажигания VW Golf, Passat",
        "Замок запалювання VW Golf, Passat 357905851",
    )
    assert generic_lock["comparisons"]["part_type"]["state"] == "MATCH"
    assert generic_lock["comparisons"]["assembly_level"]["state"] == "UNKNOWN"
    assert generic_lock["hard_stop_conflicts"] == []


def test_power_steering_reservoir_abbreviation_wins_over_pump_context() -> None:
    matrix = _matrix(
        "Бачок г/у руля VW Passat B3-B4",
        ("Бачок г/у керма Passat B3 B4 насоса гідропідсилювача KEMP"),
    )

    assert matrix["comparisons"]["part_type"]["state"] == "MATCH"
    assert matrix["comparisons"]["part_subtype"]["state"] == "MATCH"
    assert matrix["hard_stop_conflicts"] == []


@pytest.mark.parametrize(
    ("older_title", "newer_title"),
    (
        (
            "Колодки торм задние Audi-100,80,A4,A6 86-01 супорт",
            "Колодки гальмів задні Audi-100,80,A4,A6 86-01 супорт",
        ),
        ("Направляющая суппорта", "Напрямна супорта"),
        (
            "Направляющая (палец) суппорта",
            "Спрямовуюча (палець) супорта",
        ),
        (
            "Сальник распредвала VW T4",
            "Сальник розподільчого вала VW T4",
        ),
        (
            "Колодки стояночного тормоза MB Vito",
            "Колодки гальмівні стоянкового гальма Mercedes Vito",
        ),
        (
            "Сайленблок переднего рычага Peugeot",
            "Сайлентблок переднього важеля Peugeot",
        ),
        (
            "Шрус трешип внутренний Ford",
            "Шрус трьохшипний внутрішній Ford",
        ),
        (
            "Корпус термостата в сборе VW Audi",
            "Корпус термостата в зборі VW Audi",
        ),
    ),
)
def test_customer_xls_revision_language_drift_is_not_a_false_hard_stop(
    older_title: str,
    newer_title: str,
) -> None:
    assert _matrix(older_title, newer_title)["hard_stop_conflicts"] == []


@pytest.mark.parametrize(
    ("older_title", "newer_title", "dimension"),
    (
        (
            "Мотор стеклоподъемника левый Daewoo Lanos",
            "Мотор склопідйомника правий Daewoo Lanos",
            "side",
        ),
        (
            "Амортизатор задний Audi A4 B6",
            "Амортизатор передній Audi A4 B6",
            "position",
        ),
    ),
)
def test_customer_xls_revision_physical_conflicts_remain_hard_stops(
    older_title: str,
    newer_title: str,
    dimension: str,
) -> None:
    matrix = _matrix(older_title, newer_title)

    assert dimension in {
        conflict["dimension"] for conflict in matrix["hard_stop_conflicts"]
    }


def test_serviceable_and_non_serviceable_pumps_are_not_one_identity() -> None:
    matrix = _matrix(
        "Бензонасос Ford ОНС механический (не разборной)",
        "Бензонасос Ford ОНС механічний (розбірний)",
    )

    assert matrix["our_product"]["serviceability"]["values"] == ["non_serviceable"]
    assert matrix["candidate"]["serviceability"]["values"] == ["serviceable"]
    assert matrix["comparisons"]["serviceability"]["state"] == "CONFLICT"
    assert "serviceability" in {
        conflict["dimension"] for conflict in matrix["hard_stop_conflicts"]
    }

    output = _hard_stop_output(matrix["hard_stop_conflicts"])
    assert output.identity_verdict is IdentityVerdict.NOT_MATCH
    assert output.reason_codes == ["DETERMINISTIC_CONFLICT_SERVICEABILITY"]


@pytest.mark.parametrize(
    ("ours", "candidate", "expected_dimension"),
    (
        (
            "Бачек розширительный Audi A6 2.0-3.2 04->",
            "Кришка розширювального бачка Audi A6",
            "part_subtype",
        ),
        (
            "Мотор радиатора VW Sharan Ford Galaxy",
            "Фланець датчика (2-вих+1відвід і 1дат) VW/Audi",
            "part_type",
        ),
        (
            "Радіатор кондиціонера Opel Vectra B",
            "Ремень зубчатый ГРМFord Escort 1.4-1.6 CVH 97зубов.",
            "part_type",
        ),
        (
            "Ролик ГРМ Audi-80, A6 1.9 TD",
            "Ролик натяжной поликлинового ремня VW T4 1.9 D.TD",
            "part_subtype",
        ),
        (
            "Полуось VW T4 96-> внутренняя (ремкомплект)",
            "Напівось VW T4 96-> внутрішня",
            "part_subtype",
        ),
        (
            "Підшипник пер.маточ.Fiat Ducato 02->",
            "Підшипник задньої маточини Mercedes Sprinter",
            "position",
        ),
        (
            "Радиатор BMW E36 316-325 91-98 АКПП АС- 440*440",
            "Радиатор BMW E30 316i-318i 87-91 AKП АС+ 440*440",
            "climate_variant",
        ),
    ),
)
def test_customer_xls_explicit_physical_fanout_conflicts_are_hard_stops(
    ours: str,
    candidate: str,
    expected_dimension: str,
) -> None:
    matrix = _matrix(ours, candidate)

    assert expected_dimension in {
        conflict["dimension"] for conflict in matrix["hard_stop_conflicts"]
    }


def test_cyrillic_ac_both_variants_remain_unknown() -> None:
    matrix = _matrix(
        "Радиатор печки Opel Vectra АС+/-",
        "Радіатор пічки Opel Vectra",
    )

    assert matrix["our_product"]["climate_variant"]["state"] == "UNKNOWN"
    assert matrix["hard_stop_conflicts"] == []


def test_halfshaft_flange_does_not_become_complete_halfshaft() -> None:
    matrix = _matrix(
        "Флянец полуоси передней VW T5",
        "Напівось передня VW T5",
    )

    assert matrix["our_product"]["part_subtype"]["values"] == ["halfshaft_flange"]
    assert matrix["candidate"]["part_subtype"]["values"] == ["halfshaft"]
    assert "part_subtype" in {
        conflict["dimension"] for conflict in matrix["hard_stop_conflicts"]
    }


@pytest.mark.parametrize(
    ("ours", "candidate"),
    (
        (
            "Катушка зажигания VW Golf (с комутатором)",
            "Котушка запалювання VW Golf (без комутатора)",
        ),
        (
            "Ролик натяжной поликлинового ремня с механизмом",
            "Ролик натяжной поликлинового ремня без механизма",
        ),
        (
            "Рейка рулевая Mercedes W210 с серво датчиком",
            "Рейка рулевая Mercedes W210 без серво датчика",
        ),
        (
            "Ремкомплект ролика сдвижной двери с кронштейном",
            "Ремкомплект ролика сдвижной двери без кронштейна",
        ),
    ),
)
def test_explicit_component_package_conflict_stops_pricing_not_identity(
    ours: str,
    candidate: str,
) -> None:
    matrix = _matrix(ours, candidate)

    assert matrix["comparisons"]["included_components"]["state"] == "CONFLICT"
    assert "included_components" in {
        conflict["dimension"] for conflict in matrix["hard_stop_conflicts"]
    }
    output = _hard_stop_output(matrix["hard_stop_conflicts"])
    assert output.identity_verdict is IdentityVerdict.MANUAL_REVIEW
    assert output.hard_stop_conflicts[0].dimension == "included_components"


@pytest.mark.parametrize(
    ("ours", "candidate", "dimension"),
    (
        (
            "Радіатор Opel Omega B 2,0 95-00 АКПП AC- 538*371",
            "Радиатор Opel Omega B 2,0 95-00 мех.КПП AC- 532*377",
            "transmission_variant",
        ),
        (
            "Радіатор VW T5 2.5 TDI плоскі соти",
            "Радиатор VW T5 2.5 TDI круглі соти",
            "core_construction",
        ),
        (
            "Вкладыш шатун VW/Audi 5-ти цил +0.25",
            "Вкладиш шатуна VW/Audi 4-х ціл 0.25",
            "engine_cylinder_count",
        ),
        (
            "Стартер VW Golf 3-4 1.9 TDI (2KW)",
            "Стартер VW Golf 3-4 1.9 TDI (1.8KW)",
            "power_rating",
        ),
    ),
)
def test_explicit_variant_conflict_requires_review_without_denying_identity(
    ours: str,
    candidate: str,
    dimension: str,
) -> None:
    matrix = _matrix(ours, candidate)

    assert matrix["comparisons"][dimension]["state"] == "CONFLICT"
    assert dimension in {
        conflict["dimension"] for conflict in matrix["hard_stop_conflicts"]
    }
    output = _hard_stop_output(matrix["hard_stop_conflicts"])
    assert output.identity_verdict is IdentityVerdict.MANUAL_REVIEW
    assert dimension in {item.dimension for item in output.hard_stop_conflicts}


@pytest.mark.parametrize(
    ("ours", "candidate", "dimension"),
    (
        (
            "Радиатор Opel Omega B 2.0",
            "Радиатор Opel Omega B 2.0 АКПП",
            "transmission_variant",
        ),
        (
            "Стартер VW Golf 1.9 TDI",
            "Стартер VW Golf 1.9 TDI 2KW",
            "power_rating",
        ),
    ),
)
def test_missing_variant_evidence_stays_unknown_and_does_not_block(
    ours: str,
    candidate: str,
    dimension: str,
) -> None:
    matrix = _matrix(ours, candidate)

    assert matrix["comparisons"][dimension]["state"] == "UNKNOWN"
    assert dimension not in {
        conflict["dimension"] for conflict in matrix["hard_stop_conflicts"]
    }


@pytest.mark.parametrize(
    ("ours", "candidate"),
    (
        (
            "Колодки тормозные передние Ford Transit",
            "Колодки гальмівні передні Ford Transit",
        ),
        ("Диск сцепления Ford Transit", "Диск зчеплення Ford Transit"),
        ("Шланг тормозной передний VW Golf", "Шланг гальмівний передній VW Golf"),
        ("Шаровая опора VW T4", "Кульова опора VW T4"),
        ("Стойка стабилизатора Ford Transit", "Стійка стабілізатора Ford Transit"),
        ("Наконечник рулевой тяги VW Golf", "Наконечник рульової тяги VW Golf"),
        ("Рейка рулевая VW Golf", "Рейка рульова VW Golf"),
        ("Помпа водяная Audi A4", "Водяной насос Audi A4"),
        ("Бензонасос VW Passat", "Топливный насос VW Passat"),
        ("Бачек расширительный VW T5", "Бачок розширювальний VW T5"),
        ("Выключатель стоп сигнала VW", "Вимикач стоп сигналу VW"),
        ("Переключатель поворотов VW", "Перемикач поворотів VW"),
        ("Стеклоподъемник VW Golf", "Ск підймач VW Golf"),
        ("Ремень поликлиновой Audi", "Ремінь поліклінований Audi"),
        ("Провода высоковольтные Ford", "Комплект високовольтних проводів Ford"),
        ("Вкладыши шатунные Ford", "Вкладиші шатунні Ford"),
        ("Подшипник подвесной Mercedes", "Підшипник підвісний Mercedes"),
        ("Трос ручного тормоза VW", "Трос ручного гальма VW"),
        (
            "Ролик паразитный ремня ГРМ Opel",
            "Ролик ременя ГРМ обвідний Opel",
        ),
    ),
)
def test_customer_catalog_language_variants_share_part_type(
    ours: str,
    candidate: str,
) -> None:
    matrix = _matrix(ours, candidate)

    assert matrix["comparisons"]["part_type"]["state"] == "MATCH"
    assert matrix["comparisons"]["part_subtype"]["state"] == "MATCH"
    assert matrix["hard_stop_conflicts"] == []


@pytest.mark.parametrize(
    ("ours", "candidate"),
    (
        ("Колодки тормозные Ford Transit", "Диск тормозной Ford Transit"),
        ("Диск сцепления Ford Transit", "Корзина сцепления Ford Transit"),
        ("Стойка стабилизатора Ford Transit", "Втулка стабилизатора Ford Transit"),
        ("Бачок расширительный VW T5", "Бачок омывателя VW T5"),
        ("Шланг тормозной VW Golf", "Цилиндр тормозной главный VW Golf"),
        ("Выключатель стоп сигнала VW", "Переключатель поворотов VW"),
        ("Цилиндр сцепления главный Ford", "Цилиндр сцепления рабочий Ford"),
        ("Ролик натяжной ремня VW", "Ролик паразитный ремня VW"),
        ("Вкладыши шатунные Ford", "Вкладыши коренные Ford"),
    ),
)
def test_customer_catalog_adjacent_components_are_hard_stopped(
    ours: str,
    candidate: str,
) -> None:
    matrix = _matrix(ours, candidate)

    assert matrix["hard_stop_conflicts"]
    assert {conflict["dimension"] for conflict in matrix["hard_stop_conflicts"]} & {
        "part_type",
        "part_subtype",
        "assembly_level",
    }


def test_pin_and_installation_conflicts_are_hard_stops() -> None:
    matrix = _matrix(
        "Замок зажигания 6 pin в сборе правый",
        "Замок запалювання 4 pin у зборі лівий",
    )

    assert {row["dimension"] for row in matrix["hard_stop_conflicts"]} == {
        "connectors_pins",
        "side",
    }


@pytest.mark.parametrize(
    ("ours", "candidate"),
    (
        (
            "Амортизатор передний Mercedes C-Class W202 1993-2000",
            "Амортизатор MERCEDES C S202 96-/C W202 93-/E S210 96- ASHIKA",
        ),
        (
            "Радиатор печки Opel Vectra A / Calibra 1988-1995 AC+",
            "Радиатор печки THERMOTEC Opel Vectra, Astra 1843106 AC+",
        ),
        (
            "Радиатор печки Opel Vectra A / Calibra 1988-1995 AC+",
            "Радиатор печки NRF Opel Vectra 1843106, 1843105 AC+",
        ),
        (
            "Радиатор кондиционера Chevrolet Aveo T300 2011- с осушителем",
            "Радиатор кондиционера NRF Chevrolet Aveo, Cobalt 96943762",
        ),
        (
            "Радиатор кондиционера Chevrolet Aveo T300 2011- с осушителем",
            "Радиатор кондиционера Denso DCN15008",
        ),
        (
            "Прокладка ГБЦ 1.5 мм Jumper/Ducato/Movano/Boxer 2.8",
            "Прокладка ГБЦ Fiat Ducato / Peugeot Boxer / Citroen Jumper 02090F",
        ),
        (
            "Прокладка ГБЦ 1.5 мм Jumper/Ducato/Movano/Boxer 2.8",
            "Прокладка ГБЦ FIAT/IVECO 2.8TD 1.5MM Corteco",
        ),
        (
            "Датчик износа тормозных колодок Sprinter/Crafter передний",
            "Датчик тормозных колодок Sprinter/Crafter передний, 2 контакта",
        ),
        (
            "Датчик износа тормозных колодок Sprinter/Crafter передний",
            "Датчик износа тормозных колодок Sprinter/Crafter передний, 2 контакта",
        ),
        (
            "Датчик износа тормозных колодок Sprinter/Crafter передний",
            "Датчик износа тормозных колодок Mercedes W906; VW Crafter передний",
        ),
    ),
)
def test_real_prom_positive_cross_pairs_are_not_false_hard_stopped(
    ours: str,
    candidate: str,
) -> None:
    assert _matrix(ours, candidate)["hard_stop_conflicts"] == []


@pytest.mark.parametrize(
    "candidate",
    (
        "Впускний охолоджувач повітря THERMOTEC DAC006TT Fiat Scudo",
        "Охладитель наддувочного воздуха Peugeot Expert 0384N6",
        "Charge air cooler NRF 30192 Peugeot Expert",
    ),
)
def test_intercooler_title_outranks_misleading_prom_thermostat_category(
    candidate: str,
) -> None:
    matrix = _matrix(
        "Радиатор интеркулер Peugeot Expert Fiat Scudo Citroen Jumpy",
        candidate,
        category="Термостати і комплектуючі системи охолодження",
    )

    assert matrix["comparisons"]["part_type"]["state"] == "MATCH"
    assert matrix["comparisons"]["part_subtype"]["state"] == "MATCH"
    assert matrix["hard_stop_conflicts"] == []


def test_fuel_filter_pressure_is_required_and_compared() -> None:
    same = _matrix(
        "Фильтр топлива VW Audi 6.4bar",
        "Фільтр паливний VW Audi тиск 6,4 бар",
    )
    different = _matrix(
        "Фильтр топлива VW Audi 6.4bar",
        "Фільтр паливний VW Audi 4 bar",
    )
    missing = _matrix(
        "Фильтр топлива VW Audi 6.4bar",
        "Фільтр паливний VW Audi",
    )

    assert same["comparisons"]["operating_pressure"]["state"] == "MATCH"
    assert different["comparisons"]["operating_pressure"]["state"] == "CONFLICT"
    assert "operating_pressure" in {
        row["dimension"] for row in different["hard_stop_conflicts"]
    }
    assert missing["comparisons"]["operating_pressure"]["state"] == "UNKNOWN"
    assert "operating_pressure" in missing["analogue_required_dimensions"]


def test_fuel_filter_pressure_characteristic_is_normalized() -> None:
    matrix = _matrix(
        "Фильтр топлива VW Audi 6.4bar",
        "Фільтр паливний VW Audi",
        characteristics=[{"name": "Робочий тиск", "value": "6,4"}],
    )

    assert matrix["comparisons"]["operating_pressure"]["state"] == "MATCH"


def test_top_mount_bearing_phrase_outranks_generic_bearing_rule() -> None:
    matrix = _matrix(
        "Підшипник амортизатора VW Golf",
        "Підшипник опори передньої стійки VAG SNR M254.07",
    )

    assert matrix["candidate"]["part_subtype"]["values"] == ["top_mount_bearing"]
    assert matrix["comparisons"]["part_type"]["state"] == "MATCH"
    assert matrix["comparisons"]["part_subtype"]["state"] == "MATCH"
    assert matrix["hard_stop_conflicts"] == []


@pytest.mark.parametrize(
    ("ours", "candidate", "expected_dimension"),
    (
        (
            "Радиатор Ford Focus Mk3 2015-2018 1.0T",
            "Радиатор Ford Focus Mk3 2011-2014 2.0",
            "engine",
        ),
        (
            "Амортизатор передний Mercedes C-Class W202",
            "Задний амортизатор Mercedes C-Class W202",
            "position",
        ),
        (
            "Амортизатор задний Mercedes Sprinter W906",
            "Амортизатор передний Mercedes Sprinter 408D-414",
            "position",
        ),
        (
            "Прокладка ГБЦ Daewoo Matiz 1.0",
            "Прокладка ГБЦ Matiz 0.8 CRB Korea",
            "engine",
        ),
        (
            "Датчик износа тормозных колодок Sprinter передний",
            "Датчик износа тормозных колодок Mercedes W164 задний",
            "position",
        ),
        (
            "Радиатор печки Opel Vectra A AC+",
            "Радиатор печки Opel Vectra A без кондиционера",
            "climate_variant",
        ),
        (
            "Радиатор кондиционера Chevrolet Aveo T300",
            "Вентилятор основного радиатора Chevrolet Aveo T200",
            "part_type",
        ),
        (
            "Фильтр салона угольный Audi A3 / VW Passat",
            "Фильтр воздушный двигателя Audi A3 / VW Passat",
            "part_subtype",
        ),
        (
            "Прокладка выпускного коллектора VW/Audi",
            "Полный комплект прокладок двигателя VW/Audi",
            "part_subtype",
        ),
        (
            "Прокладка поддона Ford 0.9-1.1",
            "Прокладка головки блока Ford Escort 1.3",
            "part_subtype",
        ),
    ),
)
def test_real_prom_hard_negatives_have_a_deterministic_stop(
    ours: str,
    candidate: str,
    expected_dimension: str,
) -> None:
    dimensions = {
        row["dimension"] for row in _matrix(ours, candidate)["hard_stop_conflicts"]
    }
    assert expected_dimension in dimensions


def test_dimensions_are_order_independent_and_measurements_are_not_engines() -> None:
    matrix = _matrix(
        "Радиатор 652*415 для двигателя 1.9 TDI",
        "Радіатор 415x652 для двигуна 1.9 TDI",
    )
    gasket = _matrix(
        "Прокладка ГБЦ 1.5 мм двигатель 2.8",
        "Прокладка ГБЦ 1.5mm двигатель 2.8",
    )

    assert matrix["comparisons"]["technical_specs"]["state"] == "MATCH"
    assert gasket["comparisons"]["engine"] == {
        "state": "MATCH",
        "our_values": ["2.8"],
        "candidate_values": ["2.8"],
    }


def test_category_specific_dimension_tolerance_avoids_saved_false_stops() -> None:
    bearing = _matrix(
        "Подшипник передней ступицы Fiat Ducato 55*90*24",
        "Підшипник ступиці передній Fiat Ducato 55x90x23 мм",
    )
    radiator = _matrix(
        "Радиатор кондиционера Fiat Ducato 710*386",
        "Радіатор кондиціонера Fiat Ducato 710x370x16",
    )
    wrong_radiator = _matrix(
        "Радиатор Fiat Ducato 710*386",
        "Радіатор Fiat Ducato 500x300",
    )

    assert bearing["comparisons"]["technical_specs"]["state"] == "MATCH"
    assert radiator["comparisons"]["technical_specs"]["state"] == "MATCH"
    assert bearing["hard_stop_conflicts"] == []
    assert radiator["hard_stop_conflicts"] == []
    assert "technical_specs" in {
        row["dimension"] for row in wrong_radiator["hard_stop_conflicts"]
    }


def test_hub_parenthetical_bearing_spec_does_not_reclassify_the_hub() -> None:
    matrix = _matrix(
        "Ступица передняя Audi 100 88-92 (подшипник 37*82*45/43)",
        "Маточина передня Audi 100 88-92 (підшипник 37*82*45/43)",
    )

    assert matrix["our_product"]["part_subtype"]["values"] == ["wheel_hub"]
    assert matrix["candidate"]["part_subtype"]["values"] == ["wheel_hub"]
    assert matrix["hard_stop_conflicts"] == []


def test_packaging_dimensions_never_conflict_with_part_geometry() -> None:
    matrix = build_semantic_feature_matrix(
        {"name": "Радиатор Opel Combo 680*278"},
        {
            "title": "Радіатор Opel Combo Nissens 63254A",
            "characteristics": {
                "Висота упаковки": ["270"],
                "Ширина пакування": ["90"],
            },
        },
    )

    assert matrix["comparisons"]["technical_specs"]["state"] == "UNKNOWN"
    assert matrix["hard_stop_conflicts"] == []


def test_axis_characteristics_form_one_radiator_geometry() -> None:
    matrix = build_semantic_feature_matrix(
        {"name": "Радиатор Opel Combo 680*278"},
        {
            "title": "Радіатор Opel Combo Nissens 63254A",
            "characteristics": {
                "Глибина мережі [мм]": ["23"],
                "Довжина мережі [мм]": ["680"],
                "Ширина мережі [мм]": ["270"],
            },
        },
    )

    assert matrix["comparisons"]["technical_specs"]["state"] == "MATCH"
    assert matrix["hard_stop_conflicts"] == []


def test_one_anonymous_axis_is_unknown_against_full_geometry() -> None:
    matrix = build_semantic_feature_matrix(
        {"name": "Радиатор Opel Combo 680*278"},
        {
            "title": "Радіатор Opel Combo",
            "characteristics": {"Ширина мережі [мм]": ["680"]},
        },
    )

    assert matrix["comparisons"]["technical_specs"]["state"] == "UNKNOWN"
    assert matrix["hard_stop_conflicts"] == []


def test_shock_absorber_bearing_is_a_bearing_not_an_absorber() -> None:
    matrix = _matrix(
        "Подшипник верхний опорный VW Golf 5",
        "VAG 1K0412249 Підшипник амортизатора",
    )

    assert matrix["comparisons"]["part_type"]["state"] == "MATCH"
    assert matrix["comparisons"]["part_subtype"]["state"] == "MATCH"
    assert matrix["hard_stop_conflicts"] == []


def test_numbered_catalog_category_and_under_intercooler_phrase_do_not_forge_conflicts() -> (
    None
):
    exact = build_semantic_feature_matrix(
        {"name": "Радіатор Iveco 625*440", "category": "7,3 Радиаторы"},
        {
            "title": (
                "Радіатор охолодження двигуна Iveco Daily E2 "
                "2.8TDI (1996-1999) OE:93818439"
            )
        },
    )
    main_radiator = _matrix(
        "Радіатор Iveco 625*440",
        "Радіатор охолодження під інтеркулер Iveco Daily 2.8TDI",
    )

    assert exact["our_product"]["engine"]["state"] == "UNKNOWN"
    assert exact["hard_stop_conflicts"] == []
    assert main_radiator["candidate"]["part_subtype"]["values"] == [
        "engine_cooling_radiator"
    ]
    assert main_radiator["hard_stop_conflicts"] == []


@pytest.mark.parametrize(
    "candidate",
    (
        "Картина на холсте Flower shopping 90x120 см",
        "Royal Canin Urinary Care сухой корм для котов",
        'LED подсветка TV 65" V0Q8-650SM0-R0',
        "М'яч волейбольний Wilson розмір 5",
        "Дріт синій 30см d0,6см помаранчевий G-Rich",
        "Олівець графітний HB з гумкою Kite",
        "Пакети для сміття 40шт 60л міцні",
        "Блокнот А5 60л Optima спіраль",
        "Сачок для метеликів 80см",
        "Крем для лица с гиалуроновой кислотой",
        "Книга Літо, коли помер Хікару. Том 2",
        "Шкіряний пасок для джинсів синього кольору",
        "Головка торцева Yato YT-38510",
        "Шнек для насосів серії Screw 4QGD1.8",
        "Спот NOVORIO 1 Eglo 94646",
        "Ручний прожектор 6500K для кемпінгу та дачі",
        "Гачок GTV K-2343 A хром",
        "Сповіщувач пожежний ручний ИПР-1 Електронмаш",
        "Підсвітка Samsung 43 UE43TU8005K BN96-50319",
        "Накладка антиковзна для сходів Emaux",
        "Шнек для м'ясорубок ZELMER NR8",
        "Сковорода-сотейник Kamille 30 см",
        "USB кабель швидкої зарядки для iPhone та iPad",
        "Щиток молотильного барабана комбайна Claas",
        "Машина іграшкова інерція 13см",
        "Ліжко для малих порід Пет Фешн Denver",
        "Срібне намисто No Brand Серце",
        "Бюстгальтер Diorella бежевий",
        "Циркуляційний насос BADU 75 м3/год",
        "Лампа UV для манікюру та педикюру",
        "Компресор до холодильника Secop",
        "Рожевий повідець для собак",
        "Щоденник шкільний Kite",
        "Блюдо для запікання Flower bunny",
        "Набір чайний 2 предмети",
        "Рамка для сімейних фото",
        "Фільтр для пилососа Karcher",
        "Автомобільна сонцезахисна парасолька на лобове скло",
        "Модуль швидкої зарядки SW3518 Type-C",
        "Мініатюрний модуль живлення TPS61040",
        "К155ЛА13 чотири буферних логічних елемента",
        "Комплект проводки ізольований тип ВВГ",
        "Зірочка Dominoni 10164",
        "Стельовий світильник Zuma Line",
        "Пальто жіноче однотонне",
        "Шафа периферійна адресна Електронмаш",
        "Свердловинний електронасос Sprut",
        "Dekor Karpaty арт-об'єкт Ніжність квітучого дерева",
        "Ніж пластиковий посилений навантаження 60 кг",
        "Лампа для інспекційних робіт 220 В",
        "Аркуш напрямний Oros 1.300.161",
        "Втулка Manitou 940570",
        "Ручний ударний інструмент Polax",
        "Українські скарби. Валя Вздульська. Портал",
    ),
)
def test_explicit_non_automotive_search_noise_is_a_hard_stop(candidate: str) -> None:
    matrix = _matrix(
        "Шаровая опора VW Transporter T4 1991- нижняя",
        candidate,
    )

    assert matrix["comparisons"]["domain"]["state"] == "CONFLICT"
    assert "domain" in {row["dimension"] for row in matrix["hard_stop_conflicts"]}


@pytest.mark.parametrize(
    ("ours", "candidate", "expected_dimension"),
    (
        (
            "Шрус Dacia Logan наружный z21*30",
            "Привід перед. мосту Dacia Logan лів. в зб.",
            "part_type",
        ),
        (
            "Фильтр воздуха VW Passat",
            "Корпус повітряного фільтра VW Passat",
            "part_subtype",
        ),
        (
            "Нарпавляющая выжимного подшипника VW T4",
            "Сальник коробки передач VW T4",
            "part_type",
        ),
        (
            "Радиатор Opel Astra",
            "Дзеркало праве Opel Astra",
            "part_type",
        ),
        (
            "Тяга рулевая Opel Omega",
            "Буфер кабіни Scania",
            "part_type",
        ),
        (
            "Радиатор Ford Fiesta",
            "Паливний фільтр DAF 1334250",
            "part_type",
        ),
        (
            "Радиатор Audi A1",
            "Решітка в бампер Audi A1",
            "part_type",
        ),
        (
            "Радиатор Audi Q5",
            "Ручка подовжувача сидіння передня права Audi Q5",
            "part_type",
        ),
    ),
)
def test_saved_component_false_matches_are_hard_stopped(
    ours: str,
    candidate: str,
    expected_dimension: str,
) -> None:
    dimensions = {
        row["dimension"] for row in _matrix(ours, candidate)["hard_stop_conflicts"]
    }

    assert expected_dimension in dimensions


def test_structured_new_against_explicit_used_is_a_commercial_hard_stop() -> None:
    matrix = build_semantic_feature_matrix(
        {
            "name": "Фильтр воздуха VW Passat",
            "characteristics": {"Стан": ["Новий"]},
        },
        {
            "title": "Фільтр повітряний VW Passat б/у",
            "condition": "used",
        },
    )

    assert matrix["comparisons"]["condition"]["state"] == "CONFLICT"
    assert "condition" in {row["dimension"] for row in matrix["hard_stop_conflicts"]}


def test_structured_variant_fields_reach_the_semantic_gate() -> None:
    matrix = build_semantic_feature_matrix(
        {
            "name": "Амортизатор Toyota Camry",
            "side": "правий",
            "position": "задній",
            "body_variant": "седан",
            "package_quantity": 1,
            "unit_basis": "шт.",
            "year_from": 2006,
            "year_to": 2011,
        },
        {
            "title": "Амортизатор Toyota Camry",
            "side": "лівий",
            "position": "передній",
            "bodyVariant": "hatchback",
            "packageQuantity": "2.0",
            "unitBasis": "комплект",
            "yearFrom": "2012",
            "yearTo": "2015",
        },
    )

    assert matrix["our_product"]["year_interval"]["values"] == ["2006-2011"]
    assert matrix["candidate"]["year_interval"]["values"] == ["2012-2015"]
    assert (
        matrix["candidate"]["package_quantity"]["evidence"][0]["source_field"]
        == "packageQuantity"
    )
    assert {row["dimension"] for row in matrix["hard_stop_conflicts"]} >= {
        "side",
        "position",
        "body_variant",
        "package_quantity",
        "unit_basis",
    }


def test_conflicting_structured_and_text_variant_is_unknown_not_false_match() -> None:
    matrix = build_semantic_feature_matrix(
        {"name": "Амортизатор задній правий Toyota Camry"},
        {
            "title": "Амортизатор задній правий Toyota Camry",
            "side": "лівий",
            "position": "передній",
        },
    )

    for dimension in ("side", "position"):
        assert matrix["comparisons"][dimension]["state"] == "UNKNOWN"
        assert matrix["comparisons"][dimension]["source_values_ambiguous"] is True
        assert dimension not in {
            row["dimension"] for row in matrix["hard_stop_conflicts"]
        }


@pytest.mark.parametrize(
    ("ours", "candidate", "dimension"),
    (
        (
            "Амортизатор задний правый Toyota",
            "Амортизатор задний правый левый Toyota",
            "side",
        ),
        (
            "Сальник клапана 1шт",
            "Сальник клапана 1шт 2шт",
            "package_quantity",
        ),
        (
            "Термостат Ford 88°C",
            "Термостат Ford 88°C 92°C",
            "opening_temperature",
        ),
        (
            "Радиатор охлаждения 680x278",
            "Радиатор охлаждения 680x278 710x330",
            "technical_specs",
        ),
        (
            "Замок зажигания 6 pin",
            "Замок зажигания 6 pin 4 pin",
            "connectors_pins",
        ),
    ),
)
def test_multiple_sellable_values_are_unknown_not_intersection_matches(
    ours: str,
    candidate: str,
    dimension: str,
) -> None:
    """A multi-variant card cannot become a deterministic price match."""

    matrix = _matrix(ours, candidate)

    comparison = matrix["comparisons"][dimension]
    assert comparison["state"] == "UNKNOWN"
    assert comparison["source_values_ambiguous"] is True
    assert dimension not in {
        row["dimension"] for row in matrix["hard_stop_conflicts"]
    }


def test_year_intervals_match_on_overlap_and_conflict_only_when_disjoint() -> None:
    overlapping = build_semantic_feature_matrix(
        {"name": "Амортизатор Toyota", "year_from": 2006, "year_to": 2011},
        {"title": "Амортизатор Toyota", "year_from": 2008, "year_to": 2010},
    )
    disjoint = build_semantic_feature_matrix(
        {"name": "Амортизатор Toyota", "year_from": 2006, "year_to": 2011},
        {"title": "Амортизатор Toyota", "year_from": 2012, "year_to": 2015},
    )

    assert overlapping["comparisons"]["year_interval"]["state"] == "MATCH"
    assert disjoint["comparisons"]["year_interval"]["state"] == "CONFLICT"
    assert "year_interval" not in {
        row["dimension"] for row in disjoint["hard_stop_conflicts"]
    }


def test_structured_enum_separators_are_normalized() -> None:
    matrix = build_semantic_feature_matrix(
        {
            "name": "Амортизатор Toyota",
            "side": "front_right",
            "position": "front-axle",
            "body_variant": "station_wagon",
        },
        {
            "title": "Амортизатор Toyota",
            "side": "RIGHT",
            "position": "передній",
            "body_variant": "універсал",
        },
    )

    assert matrix["comparisons"]["side"]["state"] == "MATCH"
    assert matrix["comparisons"]["position"]["state"] == "MATCH"
    assert matrix["comparisons"]["body_variant"]["state"] == "MATCH"


def test_saved_used_punctuation_is_detected() -> None:
    features = extract_semantic_features(
        {"title": "Амортизатор Hyundai H1 передний правый Б.У"}
    )

    assert features["condition"].values == ("used",)


def test_damaged_marketplace_wording_is_not_a_usable_new_or_used_price() -> None:
    features = extract_semantic_features(
        {"title": "Радіатор кондиціонера Renault Scenic погнутий"}
    )

    assert features["condition"].values == ("damaged",)

    matrix = _matrix(
        "Радіатор кондиціонера Renault Scenic",
        "Радіатор кондиціонера Renault Scenic погнутий",
    )
    # Our silent side defaults to new (owner decision 2026-08-19), so a stated
    # damaged candidate is now an explicit conflict rather than an unknown —
    # strictly harder to price, which is the point of this test.
    assert matrix["comparisons"]["condition"]["state"] == "CONFLICT"
    assert "condition" in matrix["candidate_asserted_dimensions"]


@pytest.mark.parametrize(
    "title",
    (
        "A 901 501 27 82 BU _ ПАТРУБОК _ 01 79 02 03",
        "Mercedes B/U патрубок",
    ),
)
def test_latin_used_markers_from_saved_marketplace_titles_are_detected(
    title: str,
) -> None:
    features = extract_semantic_features({"title": title})

    assert features["condition"].values == ("used",)


@pytest.mark.parametrize(
    "title",
    (
        "Mercedes BU",
        "Артикул A9015012782BU",
        "Втулка BU-42",
    ),
)
def test_ambiguous_latin_bu_tokens_do_not_imply_used_condition(title: str) -> None:
    """A BU part-number fragment is not «б/у»; only the silence default fills in."""

    features = extract_semantic_features({"title": title})

    assert features["condition"].values == ("new",)
    assert [item.source_field for item in features["condition"].evidence] == [
        "marketplace_default"
    ]


def test_current_condition_classifier_rejects_stale_unknown_observation() -> None:
    observation = SimpleNamespace(
        comparison_evidence={},
        oe_verification_status="UNKNOWN",
        search_oe_norm="314893",
        extracted_oe_norms=[],
        condition_state="UNKNOWN",
        title="Амортизатор Hyundai H1 передний правый Б.У",
        description=None,
        condition_raw=None,
        comparability_hard_gate_result="MANUAL_REVIEW",
    )

    conflicts = deterministic_hard_stop_conflicts(observation)

    assert {row["dimension"] for row in conflicts} == {"condition"}


def test_plain_fan_motor_wording_does_not_disprove_complete_shroud_module() -> None:
    matrix = _matrix(
        "Мотор радіатора Fiat Doblo 1.9 Multijet",
        "Дифузор вентилятора у зборі Fiat Doblo 1.9 JTD",
    )

    assert matrix["our_product"]["part_family"]["values"] == ["cooling_fan"]
    assert matrix["our_product"]["part_subtype"]["values"] == [
        "generic_cooling_fan_motor"
    ]
    assert matrix["candidate"]["part_subtype"]["values"] == ["fan_module"]
    assert matrix["comparisons"]["part_type"]["state"] == "MATCH"
    assert matrix["comparisons"]["part_subtype"]["state"] == "UNKNOWN"
    assert matrix["comparisons"]["assembly_level"]["state"] == "UNKNOWN"
    assert matrix["hard_stop_conflicts"] == []


def test_plain_engine_cooling_fan_is_not_a_generic_radiator_motor() -> None:
    matrix = _matrix(
        "Мотор радиатора Fiat Doblo 1.9 Multijet",
        "Вентилятор охлаждения двигателя Fiat Doblo 1.9 JTD",
    )

    assert matrix["our_product"]["part_subtype"]["values"] == [
        "generic_cooling_fan_motor"
    ]
    assert matrix["candidate"]["part_subtype"]["values"] == [
        "engine_cooling_fan"
    ]
    assert matrix["comparisons"]["part_subtype"]["state"] == "CONFLICT"
    assert "part_subtype" in {
        row["dimension"] for row in matrix["hard_stop_conflicts"]
    }


@pytest.mark.parametrize(
    "title",
    (
        "Підшипник колеса VW Golf",
        "Подшипник колеса Ford Focus",
        "Колісний підшипник задньої ступиці Opel Astra",
        "Колесный подшипник передней ступицы Renault",
    ),
)
def test_wheel_bearing_wording_is_not_reduced_to_generic_bearing(title: str) -> None:
    features = extract_semantic_features({"title": title})

    assert features["part_family"].values == ("wheel_end",)
    assert features["part_subtype"].values == ("wheel_bearing",)


def test_radiator_of_the_motor_wording_is_not_a_fan_motor() -> None:
    features = extract_semantic_features(
        {
            "title": (
                "Радіатор охолодження двигуна Skoda Fabia II "
                "Радіатор мотора Шкода Фабія"
            )
        }
    )

    assert features["part_subtype"].values == ("engine_cooling_radiator",)


def test_vehicle_make_conflict_is_diagnostic_not_an_identity_hard_stop() -> None:
    matrix = _matrix(
        "Насос гидроусилителя Audi 100",
        "Насос ГУР BMW X5",
    )

    assert matrix["comparisons"]["vehicle_make"]["state"] == "CONFLICT"
    assert "vehicle_make" not in {
        row["dimension"] for row in matrix["hard_stop_conflicts"]
    }


def test_multimake_cross_platform_title_matches_on_shared_make() -> None:
    matrix = _matrix(
        "Радиатор Peugeot Boxer Citroen Jumper Fiat Ducato",
        "Радіатор Fiat Ducato",
    )

    assert matrix["comparisons"]["vehicle_make"]["state"] == "MATCH"


def test_vehicle_model_conflict_is_make_bound_and_diagnostic_only() -> None:
    matrix = _matrix(
        "Насос гидроусилителя Audi 100",
        "Насос ГУР BMW X5",
    )

    assert matrix["our_product"]["vehicle_model"]["values"] == ["audi:100"]
    assert matrix["candidate"]["vehicle_model"]["values"] == ["bmw:x5"]
    assert matrix["comparisons"]["vehicle_model"]["state"] == "CONFLICT"
    assert "vehicle_model" not in {
        row["dimension"] for row in matrix["hard_stop_conflicts"]
    }


def test_multimake_cross_platform_title_matches_on_shared_model() -> None:
    matrix = _matrix(
        "Радиатор Peugeot Boxer Citroen Jumper Fiat Ducato",
        "Радіатор Fiat Ducato",
    )

    assert matrix["comparisons"]["vehicle_model"] == {
        "state": "MATCH",
        "our_values": ["citroen:jumper", "fiat:ducato", "peugeot:boxer"],
        "candidate_values": ["fiat:ducato"],
    }


def test_generation_hint_conflict_never_becomes_deterministic_hard_stop() -> None:
    matrix = _matrix(
        "Корпус замка зажигания VW Golf III",
        "Корпус замка запалювання VW Golf IV",
    )

    assert matrix["comparisons"]["vehicle_model"]["state"] == "MATCH"
    assert matrix["comparisons"]["vehicle_generation_hint"]["state"] == "CONFLICT"
    assert "vehicle_generation_hint" not in {
        row["dimension"] for row in matrix["hard_stop_conflicts"]
    }


def test_bare_model_like_tokens_without_make_remain_unknown() -> None:
    matrix = _matrix(
        "Насос 100 A4 T5",
        "Насос 100 A4 T5",
    )

    assert matrix["our_product"]["vehicle_make"]["state"] == "UNKNOWN"
    assert matrix["our_product"]["vehicle_model"]["state"] == "UNKNOWN"
    assert matrix["our_product"]["vehicle_generation_hint"]["state"] == "UNKNOWN"


def test_audi_model_number_is_not_inferred_from_a_part_number() -> None:
    features = extract_semantic_features(
        {"title": ("Диск гальмівний Audi A4/A5/Q5 Zimmermann 100.3377.20")}
    )

    assert features["vehicle_make"].values == ("audi",)
    assert features["vehicle_model"].values == ("audi:a4",)


def test_template_description_cannot_erase_primary_side_conflict() -> None:
    matrix = build_semantic_feature_matrix(
        {
            "name": "Амортизатор передний правый Daewoo Matiz",
            "description": "В каталоге также есть левый амортизатор.",
            "characteristics": {
                "Сторона установки": ["Правий"],
            },
        },
        {
            "title": "Амортизатор передній лівий Daewoo Matiz",
        },
    )

    assert matrix["our_product"]["side"]["values"] == ["right"]
    assert matrix["candidate"]["side"]["values"] == ["left"]
    assert matrix["comparisons"]["side"]["state"] == "CONFLICT"
    assert "side" in {row["dimension"] for row in matrix["hard_stop_conflicts"]}


def test_primary_title_and_structured_side_disagreement_remains_unknown() -> None:
    matrix = build_semantic_feature_matrix(
        {
            "name": "Амортизатор передний правый Daewoo Matiz",
            "side": "left",
        },
        {
            "title": "Амортизатор передній лівий Daewoo Matiz",
        },
    )

    assert matrix["our_product"]["side"]["values"] == ["right", "left"]
    assert matrix["comparisons"]["side"]["state"] == "UNKNOWN"
    assert "side" not in {row["dimension"] for row in matrix["hard_stop_conflicts"]}


def test_shock_absorber_rod_is_not_the_complete_shock_absorber() -> None:
    matrix = _matrix(
        "Амортизатор задній Honda Accord",
        "Шток амортизатора заднього Honda Accord",
    )

    assert matrix["candidate"]["part_subtype"]["values"] == ["shock_absorber_rod"]
    assert matrix["comparisons"]["part_subtype"]["state"] == "CONFLICT"
    assert matrix["comparisons"]["assembly_level"]["state"] == "CONFLICT"


def test_used_prefix_does_not_hide_headlamp_identity() -> None:
    matrix = _matrix(
        "Радиатор Ford Focus MK3",
        "Б/У Фара права Ford Focus III",
    )

    assert matrix["candidate"]["part_subtype"]["values"] == ["headlamp"]
    assert matrix["comparisons"]["part_type"]["state"] == "CONFLICT"
    assert "part_type" in {row["dimension"] for row in matrix["hard_stop_conflicts"]}


def test_saved_residual_vehicle_models_are_diagnostic_not_hard_stops() -> None:
    toyota = _matrix(
        "Амортизатор задній Toyota Auris",
        "Амортизатор задній Toyota Prius",
    )
    chinese = _matrix(
        "Сайлентблок рычага Chery Amulet",
        "Сайлентблок рычага Geely MK",
    )

    assert toyota["comparisons"]["vehicle_model"]["state"] == "CONFLICT"
    assert chinese["comparisons"]["vehicle_make"]["state"] == "CONFLICT"
    assert chinese["comparisons"]["vehicle_model"]["state"] == "CONFLICT"
    assert not {
        "vehicle_make",
        "vehicle_model",
    } & {row["dimension"] for row in chinese["hard_stop_conflicts"]}


def test_template_description_cannot_expand_explicit_vehicle_models() -> None:
    features = extract_semantic_features(
        {
            "title": "Крышка бачка Daewoo Lanos Nexia",
            "description": ("Общий каталог также содержит товары Daewoo Matiz Nubira."),
        }
    )

    assert features["vehicle_make"].values == ("daewoo",)
    assert features["vehicle_model"].values == (
        "daewoo:lanos",
        "daewoo:nexia",
    )


def test_description_vehicle_model_remains_fallback_when_title_is_silent() -> None:
    features = extract_semantic_features(
        {
            "title": "Крышка расширительного бачка",
            "description": "Применяется на Daewoo Lanos.",
        }
    )

    assert features["vehicle_make"].values == ("daewoo",)
    assert features["vehicle_model"].values == ("daewoo:lanos",)


@pytest.mark.parametrize(
    ("ours", "candidate", "expected_platform"),
    (
        ("Fiat Ducato", "Peugeot Boxer Citroen Jumper", "sevel_large_van"),
        ("Fiat Scudo", "Peugeot Expert Citroen Jumpy", "sevel_mid_van"),
        ("Fiat Qubo", "Peugeot Bipper Citroen Nemo", "tofas_small_van"),
    ),
)
def test_badge_engineered_models_share_diagnostic_platform(
    ours: str,
    candidate: str,
    expected_platform: str,
) -> None:
    matrix = _matrix(f"Радиатор {ours}", f"Радіатор {candidate}")

    assert matrix["comparisons"]["vehicle_model"]["state"] == "CONFLICT"
    assert matrix["comparisons"]["vehicle_platform"] == {
        "state": "MATCH",
        "our_values": [expected_platform],
        "candidate_values": [expected_platform],
    }
    assert "vehicle_platform" not in {
        row["dimension"] for row in matrix["hard_stop_conflicts"]
    }


def test_package_count_does_not_create_piece_unit_for_a_set() -> None:
    matrix = _matrix(
        "Ручки дверей VW Golf комплект 4шт",
        "Ручки дверей VW Golf комплект",
    )

    assert matrix["our_product"]["package_quantity"]["values"] == ["4"]
    assert matrix["our_product"]["unit_basis"]["values"] == ["set"]
    assert matrix["comparisons"]["unit_basis"]["state"] == "MATCH"


def test_explicit_pair_is_more_precise_than_generic_set_wording() -> None:
    features = extract_semantic_features(
        {
            "title": "Пружины задние комплект 2шт",
            "measure_unit": "пара",
        }
    )

    assert features["package_quantity"].values == ("2",)
    assert features["unit_basis"].values == ("pair",)


def test_single_piece_package_retains_piece_basis() -> None:
    features = extract_semantic_features({"title": "Сальник клапана 1шт"})

    assert features["package_quantity"].values == ("1",)
    assert features["unit_basis"].values == ("piece",)


def test_characteristic_labels_supply_package_and_unit_basis() -> None:
    features = extract_semantic_features(
        {
            "title": "Термостат Ford Focus",
            "characteristics": {
                "Кількість в упаковці": ["1"],
                "Одиниця виміру": ["шт."],
            },
        }
    )

    assert features["package_quantity"].values == ("1",)
    assert features["unit_basis"].values == ("piece",)


def test_a_per_piece_listing_is_a_listing_of_one_piece() -> None:
    """Owner decision 2026-08-15: ``unit_basis = piece`` means quantity 1.

    Neither the catalogue nor the marketplace ever states a pack size, so while
    ``package_quantity`` is a required pricing dimension nothing can ever be
    admitted to a price.  The unit basis already carries what the requirement
    protects: both sides quoted per piece.
    """

    features = extract_semantic_features({"title": "Сальник клапана", "measure_unit": "шт."})

    assert features["unit_basis"].values == ("piece",)
    assert features["package_quantity"].values == ("1",)


def test_the_inference_reaches_a_unit_stated_only_as_a_characteristic() -> None:
    features = extract_semantic_features(
        {"title": "Сальник клапана", "characteristics": {"Одиниця виміру": ["шт."]}}
    )

    assert features["package_quantity"].values == ("1",)


def test_a_kit_or_pair_is_never_inferred_to_be_one_piece() -> None:
    """The guard that keeps a four-piece kit from being priced as one part."""

    for title, expected_unit in (
        ("Комплект підшипників VW LT", "set"),
        ("Пара підшипників VW LT", "pair"),
    ):
        features = extract_semantic_features({"title": title, "measure_unit": "шт."})

        assert features["unit_basis"].values == (expected_unit,)
        assert features["package_quantity"].values == ()


def test_an_explicit_pack_size_is_never_overwritten_by_the_inference() -> None:
    features = extract_semantic_features({"title": "Підшипник 4 шт.", "measure_unit": "шт."})

    assert features["package_quantity"].values == ("4",)


def test_a_stated_used_condition_is_never_overridden_by_the_default() -> None:
    """The guard the condition default must not touch.

    A card that says «б/у» anywhere has spoken; the marketplace default exists
    only for silence.  Without this case the default would be indistinguishable
    from ignoring the stated condition.
    """

    features = extract_semantic_features(
        {"title": "Фільтр повітряний VW Caddy б/у оригінал"}
    )

    assert features["condition"].values == ("used",)
    assert all(
        item.source_field != "marketplace_default"
        for item in features["condition"].evidence
    )


def test_a_silent_card_defaults_to_new_with_an_auditable_source() -> None:
    """Owner decision 2026-08-19: an unstated condition means a new part.

    Measured on run ``c2d5e78b``: 32 of 70 competitor cards say nothing about
    condition, and 28 of 70 observations were held out of the price cohort by
    that silence alone.  A marketplace listing sells new goods unless it says
    otherwise; used listings say so and are caught by the pattern above and by
    the ``is_used`` cohort rejection upstream.
    """

    features = extract_semantic_features({"title": "Фільтр повітряний VW Caddy"})

    assert features["condition"].values == ("new",)
    assert [item.source_field for item in features["condition"].evidence] == [
        "marketplace_default"
    ]


def test_a_stated_new_condition_is_evidence_not_the_default() -> None:
    features = extract_semantic_features(
        {
            "title": "Фільтр повітряний VW Caddy",
            "characteristics": {"Стан": ["Новий"]},
        }
    )

    assert features["condition"].values == ("new",)
    assert all(
        item.source_field != "marketplace_default"
        for item in features["condition"].evidence
    )


def test_the_default_resolves_the_condition_comparison_to_a_match() -> None:
    """The money case: our stated «Новий» against a silent competitor card."""

    matrix = build_semantic_feature_matrix(
        {"name": "Фільтр повітряний VW Caddy", "characteristics": {"Стан": ["Новий"]}},
        {"title": "Фільтр повітряний VW Caddy III 1.9TDI"},
    )

    assert matrix["comparisons"]["condition"]["state"] == "MATCH"
    assert "condition" not in {
        row["dimension"] for row in matrix["hard_stop_conflicts"]
    }


def test_a_listing_with_no_unit_basis_stays_unknown() -> None:
    """Silence must stay silence: an unstated unit cannot become quantity 1."""

    features = extract_semantic_features({"title": "Підшипник вискомуфти VW LT"})

    assert features["unit_basis"].values == ()
    assert features["package_quantity"].values == ()


def test_the_three_pricing_dimensions_match_when_both_sides_state_them() -> None:
    """The whole point: this is what admission to a price cohort requires."""

    comparisons = build_semantic_feature_matrix(
        {
            "name": "Подшипник ролика промеж (термомуфты) Audi-100 91-97",
            "brand": "KEMP",
            "measure_unit": "шт.",
            "characteristics": {"Стан": ["Новий"]},
        },
        {
            "title": "Підшипник вискомуфти VW LT/Crafter 2.5TDI",
            "measure_unit": "шт.",
            "condition": "Новий",
        },
    )["comparisons"]

    for dimension in ("condition", "package_quantity", "unit_basis"):
        assert comparisons[dimension]["state"] == "MATCH", dimension


def test_compact_catalogue_years_are_normalized_and_compared() -> None:
    overlap = _matrix(
        "Радиатор Ford 95-00",
        "Радіатор Ford 1997-1999",
    )
    disjoint = _matrix(
        "Радиатор Ford 84-93",
        "Радіатор Ford 2004-2010",
    )

    assert overlap["our_product"]["year_interval"]["values"] == ["1995-2000"]
    assert overlap["comparisons"]["year_interval"]["state"] == "MATCH"
    assert disjoint["comparisons"]["year_interval"]["state"] == "CONFLICT"
    assert "year_interval" not in {
        row["dimension"] for row in disjoint["hard_stop_conflicts"]
    }


@pytest.mark.parametrize(
    "title",
    (
        "Радиатор Ford 1.4-1.6",
        "Датчик 01-86-02-18",
        "Подшипник 31-110",
        "Артикул 20-95",
    ),
)
def test_compact_year_parser_rejects_decimals_codes_and_implausible_spans(
    title: str,
) -> None:
    features = extract_semantic_features({"title": title})

    assert features["year_interval"].values == ()


@pytest.mark.parametrize(
    ("title", "family", "subtype", "assembly"),
    (
        (
            "Насос вакуумний MB OM601-602",
            "brake_vacuum",
            "brake_vacuum_pump",
            "complete_assembly",
        ),
        (
            "Радiатор MERCEDES-BENZ V-CLASS NISSENS",
            "radiator",
            "engine_cooling_radiator",
            "single_part",
        ),
        (
            "Радiатор кондицiонера PEUGEOT 406",
            "radiator",
            "ac_condenser",
            "single_part",
        ),
        (
            "Ручка зовнішня підіймальна VW Golf 2",
            "door_hardware",
            "door_handle",
            "single_part",
        ),
        (
            "Вклад.шатун.ком/кт +0.50",
            "engine_bearing",
            "connecting_rod_bearing",
            "set",
        ),
        (
            "Наконечн.р.т.Logan левый",
            "steering",
            "tie_rod_end",
            "single_part",
        ),
        (
            "Накинечник керма VW Transporter",
            "steering",
            "tie_rod_end",
            "single_part",
        ),
        (
            "Кришка бачка охолоджуючої рідини Opel",
            "coolant_reservoir",
            "expansion_tank_cap",
            "component",
        ),
        (
            "Стійка стаб. RENAULT TRAFIC",
            "suspension",
            "stabilizer_link",
            "single_part",
        ),
    ),
)
def test_saved_marketplace_orthography_maps_to_closed_taxonomy(
    title: str,
    family: str,
    subtype: str,
    assembly: str,
) -> None:
    features = extract_semantic_features({"title": title})

    assert features["part_family"].values == (family,)
    assert features["part_subtype"].values == (subtype,)
    assert features["assembly_level"].values == (assembly,)


@pytest.mark.parametrize(
    "title",
    (
        "Насос вакуумної упаковки продуктів",
        "Стойка стабильного напряжения",
    ),
)
def test_marketplace_abbreviation_variants_do_not_capture_adjacent_noise(
    title: str,
) -> None:
    features = extract_semantic_features({"title": title})

    assert features["part_family"].values == ()


def test_furniture_handle_is_generic_but_explicitly_non_automotive() -> None:
    features = extract_semantic_features({"title": "Ручка зовнішня для меблів"})

    assert features["part_family"].values == ("generic_handle",)
    assert features["part_subtype"].values == ()
    assert features["domain"].values == ("non_automotive",)


def test_generic_bushing_set_stops_single_bushing_price_without_claiming_subtype() -> (
    None
):
    matrix = _matrix(
        "Сайлентблок рычага переднего Chevrolet Aveo",
        "Комплект передніх сайлентблоків Chevrolet Aveo",
    )

    # Generic set wording does not prove which suspension-bushing subtype it
    # contains.  Family equality remains UNKNOWN; the explicit
    # set-versus-single contradiction is sufficient to stop pricing.
    assert matrix["comparisons"]["part_type"]["state"] == "UNKNOWN"
    assert matrix["comparisons"]["part_subtype"]["state"] == "UNKNOWN"
    assert matrix["comparisons"]["assembly_level"]["state"] == "CONFLICT"
    assert {row["dimension"] for row in matrix["hard_stop_conflicts"]} == {
        "assembly_level"
    }


def test_generic_bushing_set_remains_distinct_from_complete_control_arm() -> None:
    matrix = _matrix(
        "Рычаг передний Chevrolet Aveo",
        "Комплект передніх сайлентблоків Chevrolet Aveo",
    )

    # A generic bushing set is not the same asserted family as a complete arm.
    # Keep the family comparison conservative while explicit subtype and
    # assembly contradictions stop pricing.
    assert matrix["comparisons"]["part_type"]["state"] == "UNKNOWN"
    assert matrix["comparisons"]["part_subtype"]["state"] == "CONFLICT"
    assert {row["dimension"] for row in matrix["hard_stop_conflicts"]} == {
        "part_subtype",
        "assembly_level",
    }


def test_automotive_generic_hydraulic_pump_adds_family_evidence_only() -> None:
    matrix = _matrix(
        "Насос гидроусилителя Mercedes W202 W210",
        "Насос гідравлічний MEYLE 0146310005 MERCEDES C-Class, MERCEDES E-Class",
    )

    assert matrix["candidate"]["part_family"]["values"] == ["generic_hydraulic_pump"]
    assert matrix["candidate"]["part_subtype"]["values"] == []
    assert matrix["candidate"]["assembly_level"]["values"] == []
    assert matrix["comparisons"]["part_type"]["state"] == "UNKNOWN"
    assert matrix["hard_stop_conflicts"] == []


def test_generic_hydraulic_pump_requires_automotive_context() -> None:
    features = extract_semantic_features(
        {"title": "Насос гідравлічний для преса 20 тонн"}
    )

    assert features["part_family"].values == ()
    assert features["domain"].values == ()


def test_chassis_linkage_category_adds_family_evidence_only() -> None:
    matrix = _matrix(
        "Рычаг передний Audi A4",
        (
            "Важілі та тяги ASMETAL 23AU0230 Audi A4, A8, A6; "
            "Skoda Superb; Volkswagen Passat"
        ),
    )

    assert matrix["candidate"]["part_family"]["values"] == ["chassis_linkage"]
    assert matrix["candidate"]["part_subtype"]["values"] == []
    assert matrix["candidate"]["assembly_level"]["values"] == []
    assert matrix["comparisons"]["part_type"]["state"] == "UNKNOWN"
    assert matrix["hard_stop_conflicts"] == []


def test_chassis_linkage_disproves_an_unrelated_radiator() -> None:
    matrix = _matrix(
        "Радиатор Audi A4",
        "Важілі та тяги ASMETAL Audi A4 Volkswagen Passat",
    )

    assert matrix["comparisons"]["part_type"]["state"] == "CONFLICT"
    assert {row["dimension"] for row in matrix["hard_stop_conflicts"]} == {"part_type"}


def test_chassis_linkage_wording_requires_automotive_context() -> None:
    features = extract_semantic_features(
        {"title": "Важілі та тяги механізму промислового верстата"}
    )

    assert features["part_family"].values == ()
    assert features["domain"].values == ()


def test_bare_handle_title_disproves_radiator_without_claiming_handle_subtype() -> None:
    matrix = _matrix(
        "Радиатор HYUNDAI TUCSON 485 x 467 x 26mm",
        "Ручка 6066-06 хром",
    )

    assert matrix["candidate"]["part_family"]["values"] == ["generic_handle"]
    assert matrix["candidate"]["part_subtype"]["values"] == []
    assert matrix["comparisons"]["part_type"]["state"] == "CONFLICT"
    assert {row["dimension"] for row in matrix["hard_stop_conflicts"]} == {"part_type"}


def test_bare_handle_title_does_not_disprove_a_specific_door_handle() -> None:
    matrix = _matrix(
        "Ручка двери VW Golf",
        "Ручка 6066-06 хром",
    )

    assert matrix["comparisons"]["part_type"]["state"] == "UNKNOWN"
    assert matrix["comparisons"]["part_subtype"]["state"] == "UNKNOWN"
    assert matrix["hard_stop_conflicts"] == []


def test_fan_motor_without_impeller_is_not_a_complete_fan_assembly() -> None:
    features = extract_semantic_features(
        {"title": ("Мотор радиатора Renault 9 11 21 Clio Espace (без крыльчатки)")}
    )

    assert features["part_family"].values == ("cooling_fan",)
    assert features["part_subtype"].values == ("cooling_fan_motor",)
    assert features["assembly_level"].values == ("component",)
    assert features["included_components"].values == ("without_impeller",)


def test_generic_fan_motor_preserves_engine_vs_cabin_uncertainty() -> None:
    engine = _matrix(
        "Мотор радиатора Renault (без крыльчатки)",
        "Мотор вентилятора Renault 9 11 19 25",
    )
    cabin = _matrix(
        "Мотор печки Renault",
        "Мотор вентилятора Renault 9 11 19 25",
    )

    for matrix in (engine, cabin):
        assert matrix["comparisons"]["part_type"]["state"] == "UNKNOWN"
        assert matrix["comparisons"]["part_subtype"]["state"] == "UNKNOWN"
        assert matrix["comparisons"]["assembly_level"]["state"] == "UNKNOWN"
        assert matrix["hard_stop_conflicts"] == []


def test_fan_motor_with_and_without_impeller_is_a_commercial_conflict() -> None:
    matrix = _matrix(
        "Мотор радиатора Renault (без крыльчатки)",
        "Мотор вентилятора Renault с крыльчаткой",
    )

    assert matrix["comparisons"]["included_components"]["state"] == "CONFLICT"
    assert {row["dimension"] for row in matrix["hard_stop_conflicts"]} == {
        "included_components"
    }


def test_fan_motor_missing_impeller_fact_is_unknown_not_a_complete_assembly() -> None:
    matrix = _matrix(
        "Мотор радиатора VW Golf 2 (без крыльчатки)",
        "Мотор радиатора VW Golf 2 2-х скор.",
    )

    assert matrix["comparisons"]["part_type"]["state"] == "MATCH"
    assert matrix["comparisons"]["part_subtype"]["state"] == "UNKNOWN"
    assert matrix["comparisons"]["assembly_level"]["state"] == "UNKNOWN"
    assert matrix["comparisons"]["included_components"]["state"] == "UNKNOWN"
    assert matrix["hard_stop_conflicts"] == []


def test_cross_revision_fan_motor_impeller_disagreement_remains_hard() -> None:
    matrix = _matrix(
        "Мотор радиатора Renault (без крыльчатки)",
        "Мотор радіатора Renault (з крильчаткою)",
    )

    assert matrix["comparisons"]["part_type"]["state"] == "MATCH"
    assert matrix["comparisons"]["part_subtype"]["state"] == "CONFLICT"
    assert matrix["comparisons"]["assembly_level"]["state"] == "CONFLICT"
    assert matrix["comparisons"]["included_components"]["state"] == "CONFLICT"
    assert {row["dimension"] for row in matrix["hard_stop_conflicts"]} == {
        "part_subtype",
        "assembly_level",
        "included_components",
    }


def test_plain_fan_motor_and_standalone_impeller_are_distinct_components() -> None:
    matrix = _matrix(
        "Мотор радиатора Opel Vectra B без рамки",
        "Крыльчатка вентилятора Opel Vectra B 390 mm",
    )

    assert matrix["comparisons"]["part_type"]["state"] == "MATCH"
    assert matrix["comparisons"]["part_subtype"]["state"] == "CONFLICT"
    assert matrix["comparisons"]["assembly_level"]["state"] == "UNKNOWN"
    assert {row["dimension"] for row in matrix["hard_stop_conflicts"]} == {
        "part_subtype"
    }


def test_tensioner_module_roller_proves_belt_family_without_inventing_subtype() -> None:
    matrix = _matrix(
        "Ролик паразитний ремня ГРМ Audi A4 2.4",
        "Ролик модуля натягувача ременя Audi A4",
    )

    assert matrix["candidate"]["part_family"]["values"] == ["belt_drive"]
    assert matrix["candidate"]["part_subtype"]["values"] == []
    assert matrix["comparisons"]["part_type"]["state"] == "MATCH"
    assert matrix["comparisons"]["part_subtype"]["state"] == "UNKNOWN"
    assert matrix["comparisons"]["assembly_level"]["state"] == "UNKNOWN"
    assert matrix["hard_stop_conflicts"] == []


def test_bare_hydraulic_booster_proves_steering_family_only() -> None:
    matrix = _matrix(
        "Насос гидроусилителя Audi A4",
        "Гідропідсилювач VW Passat B5 Audi A4",
    )

    assert matrix["candidate"]["part_family"]["values"] == ["steering"]
    assert matrix["candidate"]["part_subtype"]["values"] == []
    assert matrix["comparisons"]["part_type"]["state"] == "MATCH"
    assert matrix["comparisons"]["part_subtype"]["state"] == "UNKNOWN"
    assert matrix["comparisons"]["assembly_level"]["state"] == "UNKNOWN"
    assert matrix["hard_stop_conflicts"] == []


def test_hydraulic_brake_booster_is_not_forced_into_steering() -> None:
    features = extract_semantic_features({"title": "Гідропідсилювач гальм Mercedes"})

    assert features["part_family"].values == ()


def test_power_steering_pump_repair_kit_is_not_the_complete_pump() -> None:
    repair_kit = _matrix(
        "Ремкомплект насоса гидроусилителя Mercedes",
        "Комплект прокладок насос ГУР Mercedes",
    )
    complete_pump = _matrix(
        "Ремкомплект насоса гидроусилителя Mercedes",
        "Насос ГУР Mercedes",
    )

    assert repair_kit["comparisons"]["part_subtype"]["state"] == "MATCH"
    assert complete_pump["comparisons"]["part_subtype"]["state"] == "CONFLICT"


def test_full_and_lower_engine_gasket_sets_are_commercially_distinct() -> None:
    matrix = _matrix(
        "Прокладки двигателя VW Audi 1.8T комплект полный",
        "Комплект прокладок (нижній) Audi A4 VW Passat 1.8T",
    )

    assert matrix["comparisons"]["part_type"]["state"] == "MATCH"
    assert matrix["comparisons"]["included_components"]["state"] == "CONFLICT"
    assert "included_components" in {
        row["dimension"] for row in matrix["hard_stop_conflicts"]
    }


def test_json_encoded_characteristics_are_parsed_without_identity_inference() -> None:
    matrix = build_semantic_feature_matrix(
        {
            "name": "Фильтр воздуха VW Passat",
            "characteristics": '{"Стан": ["Новий"]}',
        },
        {
            "title": "Фільтр повітряний VW Passat б/у",
        },
    )

    assert matrix["our_product"]["condition"]["values"] == ["new"]
    assert matrix["candidate"]["condition"]["values"] == ["used"]
    assert matrix["comparisons"]["condition"]["state"] == "CONFLICT"


def test_stabilizer_link_wording_variants_remain_same_subtype() -> None:
    matrix = _matrix(
        "Стойка стабилизатора заднего Mercedes Sprinter",
        "Тяга стабілізатора заднього Mercedes Sprinter",
    )

    assert matrix["comparisons"]["part_subtype"]["state"] == "MATCH"
    assert matrix["hard_stop_conflicts"] == []


def test_saved_automotive_spelling_variants_gain_same_family_evidence() -> None:
    pairs = (
        (
            "Вакумный насос тормозов Mercedes Sprinter",
            "Вакуумний насос Mercedes Sprinter",
        ),
        (
            "Ремень генератора Ford Transit",
            "Ремінь поліклиновий Ford Transit",
        ),
        (
            "Помпа VW Crafter",
            "Водяний насос VW Crafter",
        ),
        (
            "Датчик положения распредвала Mercedes",
            "Camshaft position sensor Mercedes",
        ),
        (
            "Бендикс Mercedes W124",
            "Бендикс стартера Mercedes W124",
        ),
    )

    for ours, candidate in pairs:
        matrix = _matrix(ours, candidate)
        assert matrix["comparisons"]["part_type"]["state"] == "MATCH"
        assert matrix["hard_stop_conflicts"] == []


def test_marketplace_piece_unit_does_not_erase_explicit_set_boundary() -> None:
    matrix = build_semantic_feature_matrix(
        {"name": "Сайлентблок рычага Chevrolet Aveo 1 шт"},
        {
            "title": "Комплект сайлентблоків Chevrolet Aveo",
            "measure_unit": "шт.",
        },
    )

    assert matrix["candidate"]["unit_basis"]["values"] == ["set"]
    assert matrix["comparisons"]["unit_basis"]["state"] == "CONFLICT"


def test_vehicle_model_new_beetle_does_not_manufacture_new_condition() -> None:
    """The model name «New Beetle» must never become condition evidence.

    Our side does end up ``new`` — but from the marketplace-silence default,
    not from the word «New» in the title; the candidate's stated «б/у» keeps
    the comparison an honest conflict.
    """

    matrix = _matrix(
        "Фильтр воздуха VW New Beetle",
        "Фільтр повітряний VW New Beetle б/у",
    )

    assert [
        item["source_field"]
        for item in matrix["our_product"]["condition"]["evidence"]
    ] == ["marketplace_default"]
    assert matrix["candidate"]["condition"]["values"] == ["used"]
    assert matrix["comparisons"]["condition"]["state"] == "CONFLICT"


@pytest.mark.parametrize(
    ("ours", "candidate", "expected_dimension"),
    (
        (
            "Датчик темпер.VW Golf 4-х контактный",
            "Разъем датчика температуры VW Golf",
            "part_type",
        ),
        (
            "Датчик темпер.VW Golf 4-х контактный",
            "Конектор датчика температури VW Golf",
            "part_type",
        ),
        (
            "Радиатор Opel Vectra 2.5",
            "Кришка 0013001810 запірна паливного бака",
            "part_type",
        ),
        (
            "Генератор щеточный узел Daewoo Lanos",
            "Лямбда зонд, датчик кислорода Honda Civic",
            "part_type",
        ),
        (
            "Втулка стабилизатора Ford Transit",
            "Форсунка Peugeot 407 2.7 D",
            "part_type",
        ),
        (
            "Подушка верхняя опорная Ford Transit",
            "Ремкомплект клапанной крышки Peugeot",
            "part_type",
        ),
        (
            "Пружина задняя BMW E46",
            "Важіль задній лівий Mercedes W164",
            "part_subtype",
        ),
        (
            "Ролик двери сдвижной Opel Combo",
            "Электрический топливный насос Mercedes",
            "part_type",
        ),
        (
            "Корзина сцепления Opel Astra",
            "Комплект зчеплення Opel Astra",
            "part_subtype",
        ),
        (
            "Мотор радиатора Opel Vectra",
            "Вентилятор кабiни кондиц. NISSENS",
            "part_type",
        ),
        (
            "Радиатор кондиционера Honda Accord",
            "Панель приладів hybrid Kia Optima",
            "part_type",
        ),
        (
            "Термостат Ford Transit 1.8D",
            "Датчик тиску масла Audi A6",
            "part_type",
        ),
        (
            "Стартер Ford Escort",
            "З/ч на стартер: бендикс, щетки, якорь",
            "part_subtype",
        ),
        (
            "Рулевая рейка Mercedes Sprinter",
            "Ремкомплект рулевой рейки Mercedes Sprinter",
            "part_subtype",
        ),
        (
            "Насос гидроусилителя Ford Transit",
            "Шків насоса ГУР Ford Transit",
            "part_subtype",
        ),
        (
            "Радиатор EGR Renault Master 2.3",
            "Радиатор охлаждения двигателя Renault Master",
            "part_type",
        ),
        (
            "Мотор радиатора Opel Vectra",
            "Крильчатка вентилятора Opel Vectra",
            "part_subtype",
        ),
        (
            "Сальник распредвала VW Golf",
            "Сальник півосі VW Golf",
            "part_subtype",
        ),
        (
            "Подшипник передней ступицы Audi A4",
            "Передняя ступица Audi A4",
            "part_subtype",
        ),
        (
            "Амортизатор задний Mitsubishi Lancer",
            "Вилка КПП Mitsubishi Lancer",
            "part_type",
        ),
    ),
)
def test_explicit_cross_category_noise_is_a_hard_stop(
    ours: str,
    candidate: str,
    expected_dimension: str,
) -> None:
    dimensions = {
        row["dimension"] for row in _matrix(ours, candidate)["hard_stop_conflicts"]
    }
    assert expected_dimension in dimensions


def test_long_tv_backlight_title_still_counts_as_non_automotive() -> None:
    matrix = _matrix(
        "Радиатор Fiat Qubo 1.4 HDI",
        (
            "LED подсветка JL.D580A1330-003FS-M_V02 "
            "HD580Y1U91-TBL2 2021041601 Hisense 58R6E"
        ),
    )

    assert "domain" in {row["dimension"] for row in matrix["hard_stop_conflicts"]}


def test_control_arm_bushing_is_not_misread_as_the_complete_arm() -> None:
    same_bushing = _matrix(
        "Сайлентблок рычага Audi 80",
        "Салінблок ричага Audi 80",
    )
    different_assembly = _matrix(
        "Сайлентблок рычага Audi 80",
        "Рычаг подвески Audi 80 в сборе",
    )
    engine_mount = _matrix(
        "Подушка двигателя Peugeot Partner",
        "Важіль підвіски Peugeot Partner",
    )

    assert same_bushing["comparisons"]["part_subtype"]["state"] == "MATCH"
    assert same_bushing["hard_stop_conflicts"] == []
    assert "part_subtype" in {
        row["dimension"] for row in different_assembly["hard_stop_conflicts"]
    }
    assert "part_type" in {
        row["dimension"] for row in engine_mount["hard_stop_conflicts"]
    }


def test_window_switch_language_and_abbreviation_variants_match() -> None:
    matrix = _matrix(
        "Кнопка стеклоподъемника Fiat Doblo левая одинарная",
        "Кнопка ск/підймач Fiat DOBLO ліва одинарна",
    )

    assert matrix["comparisons"]["part_type"]["state"] == "MATCH"
    assert matrix["comparisons"]["part_subtype"]["state"] == "MATCH"
    assert matrix["hard_stop_conflicts"] == []


def test_window_control_module_is_not_a_window_switch() -> None:
    matrix = _matrix(
        "Блок управления стеклоподъемниками Volkswagen Golf Mk7",
        "Кнопки склопідіймача Volkswagen Golf 7",
    )

    assert matrix["our_product"]["part_subtype"]["values"] == [
        "window_control_module"
    ]
    assert matrix["candidate"]["part_subtype"]["values"] == ["window_switch"]
    assert {row["dimension"] for row in matrix["hard_stop_conflicts"]} >= {
        "part_subtype",
        "assembly_level",
    }


def test_transliterated_ac_radiator_matches_ac_condenser() -> None:
    matrix = _matrix(
        "KEMP radiator kondicionera Mazda 6 13-17 2.0 2.5 GHR161480B",
        "Радіатор кондиціонера Mazda 6 2.2 D 12->",
    )

    assert matrix["comparisons"]["part_type"]["state"] == "MATCH"
    assert matrix["comparisons"]["part_subtype"]["state"] == "MATCH"
    assert matrix["hard_stop_conflicts"] == []


def test_trunk_lid_gas_spring_is_distinct_from_suspension_shock() -> None:
    same = _matrix(
        "Амортизатор крышки багажника VW Touran",
        "Амортизатор багажника VW Touran",
    )
    suspension = _matrix(
        "Амортизатор крышки багажника VW Touran",
        "Амортизатор задний подвески VW Touran",
    )

    assert same["comparisons"]["part_type"]["state"] == "MATCH"
    assert same["hard_stop_conflicts"] == []
    assert "part_type" in {
        row["dimension"] for row in suspension["hard_stop_conflicts"]
    }


@pytest.mark.parametrize(
    ("ours", "candidate"),
    (
        (
            "Радиатор печки Renault Trafic Opel Vivaro",
            "Радіатор печі Renault Trafic; радіатор обігрівача салону",
        ),
        (
            "Радиатор печки Skoda Felicia",
            "Радиатор отопителя Skoda Felicia",
        ),
        (
            "Радиатор VW Golf 1.6-2.0 AC+ с кондиционером",
            "Радіатор охолодження VW Golf 1.6-2.0",
        ),
        (
            "Корпус термостата c термостатом Ford Transit 2.0D",
            "Корпус термостата у зборі Ford Transit 2.0D",
        ),
        (
            "Радиатор кондиционера VW Crafter",
            "Радіатор конденсатора Mercedes Sprinter, VW Crafter",
        ),
        (
            "Подушка верхняя опорная Ford Transit",
            "Опора переднего амортизатора Ford Transit",
        ),
        (
            "Амортизатор крышки багажника Citroen C5",
            "Газова пружина Citroen C5",
        ),
        (
            "Радиатор кондиционера Opel Vectra 1.9-2.2 DTI",
            "Радіатор кондиціонера Opel Vectra 2.2 DTI",
        ),
        (
            "Направляющая суппорта (ремкомплект) Mercedes Sprinter",
            "Ремкомплект супорту Mercedes Sprinter",
        ),
    ),
)
def test_saved_cut_language_variants_are_not_false_hard_stopped(
    ours: str,
    candidate: str,
) -> None:
    assert _matrix(ours, candidate)["hard_stop_conflicts"] == []


def test_prom_availability_vocabulary_and_conflicts_fail_closed() -> None:
    assert _availability(None, "avail") is True
    assert _availability(None, "not_avail") is False
    assert _availability(True, "avail") is True
    assert _availability(False, "not_avail") is False
    assert _availability(False, "avail") is None
    assert _availability(True, "not_avail") is None


def test_deterministic_component_conflict_skips_optimistic_llm_path() -> None:
    item = SimpleNamespace(
        name="Корпус замка зажигания VW Golf, Passat 88-96",
        category="Замки зажигания",
        description=None,
        brand="KEMP",
        characteristics_raw={},
    )
    observation = SimpleNamespace(
        title="357905851D контактна група Vw Golf 3",
        description=None,
        brand_raw=None,
        condition_raw=None,
        condition_state="UNKNOWN",
        is_available=True,
        candidate_snapshot={"product": {}},
        comparison_evidence={},
        oe_verification_status="UNKNOWN",
        search_oe_norm="357905851D",
        extracted_oe_norms=[],
        comparability_hard_gate_result="MANUAL_REVIEW",
    )

    conflicts = deterministic_hard_stop_conflicts(observation, item=item)

    assert {row["dimension"] for row in conflicts} == {
        "part_subtype",
        "assembly_level",
    }


def _identity_match(level: ComparabilityMatchLevel) -> LLMComparabilityOutput:
    return LLMComparabilityOutput(
        identity_verdict=IdentityVerdict.MATCH,
        match_level=level,
        identity_match_score=Decimal("0.95"),
        decision_confidence=Decimal("0.90"),
        image_consistency=ImageConsistency.UNAVAILABLE,
        rationale="The identity evidence supports the declared match level.",
        reason_codes=["IDENTITY_MATCH"],
        dimension_findings=[
            ReviewDimensionFinding(
                dimension="part_type",
                outcome=FindingOutcome.MATCH,
                explanation="Both products are radiators.",
            )
        ],
        hard_stop_conflicts=[],
    )


def _prepared_with_matrix(
    matrix: dict,
    *,
    category: str = "radiator",
    oe_status: str = "VERIFIED_CROSS",
    verified_cross: bool = True,
) -> _PreparedReview:
    dimensions = {
        name: {"state": "MATCH"}
        for name in (
            "oe_reference",
            "part_type",
            "condition",
            "package_quantity",
            "unit_basis",
        )
    }
    return _PreparedReview(
        workspace_id=uuid4(),
        observation_id=uuid4(),
        catalog_item_id=uuid4(),
        request_key="a" * 64,
        input_hash="b" * 64,
        attempt_no=1,
        input_snapshot={
            "our_product": {"category": category, "oe_norm": "SEED1"},
            "candidate": {
                "is_available": True,
                "oe_verification_status": oe_status,
                "verified_matched_oe_norm": "CANDIDATE1",
            },
            "deterministic_context": {
                "comparability_hard_gate_result": "PASS",
                "automatic_eligible": True,
                "seller_identity_verified": True,
                "source_provenance_verified": True,
                "semantic_feature_matrix": matrix,
            },
            "verified_cross_edge": (
                {
                    "cross_link_id": "00000000-0000-0000-0000-000000000001",
                    "seed_code": "SEED1",
                    "candidate_code": "CANDIDATE1",
                    "validation_status": "CONFIRMED",
                    "stable_seller_id_count": 2,
                    "automatic_eligible": True,
                }
                if verified_cross
                else None
            ),
            "deterministic_evidence": {"dimensions": dimensions},
        },
        image_urls=(),
        hard_stop_conflicts=(),
        is_owned=False,
        is_used=False,
        cohort_role="TARGET_MARKET",
    )


def test_analogue_needs_category_specs_while_exact_identity_does_not_invent_them() -> (
    None
):
    matrix = _matrix(
        "Радіатор Iveco 625*440",
        "Радіатор Iveco Daily OE:93818439",
    )
    analogue_prepared = _prepared_with_matrix(matrix)
    exact_prepared = _prepared_with_matrix(
        matrix,
        oe_status="VERIFIED_EXACT",
        verified_cross=False,
    )

    analogue = derive_pricing_admission(
        analogue_prepared,
        _identity_match(ComparabilityMatchLevel.ACCEPTABLE_ANALOGUE),
    )
    exact = derive_pricing_admission(
        exact_prepared,
        _identity_match(ComparabilityMatchLevel.EXACT),
    )

    assert analogue.status is PricingAdmission.MANUAL_REVIEW
    assert set(analogue.reason_codes) >= {
        "PRICING_EVIDENCE_MISSING_ENGINE",
        "PRICING_EVIDENCE_MISSING_INLET_OUTLET",
        "PRICING_EVIDENCE_MISSING_TECHNICAL_SPECS",
    }
    assert exact.status is PricingAdmission.ADMITTED


def test_exact_oe_still_requires_seed_asserted_sellable_configuration() -> None:
    matrix = _matrix(
        "Корпус замка зажигания VW Golf 357905851D",
        "Замок зажигания VW Golf 357905851D",
    )

    decision = derive_pricing_admission(
        _prepared_with_matrix(
            matrix,
            category="other",
            oe_status="VERIFIED_EXACT",
            verified_cross=False,
        ),
        _identity_match(ComparabilityMatchLevel.EXACT),
    )

    assert decision.status is PricingAdmission.MANUAL_REVIEW
    assert decision.reason_codes == (
        "PRICING_EVIDENCE_MISSING_ASSEMBLY_LEVEL",
        "PRICING_EVIDENCE_MISSING_PART_SUBTYPE",
    )


def test_exact_oe_with_seed_asserted_configuration_remains_priceable() -> None:
    matrix = _matrix(
        "Корпус замка зажигания VW Golf 357905851D",
        "Корпус замка зажигания VW Golf 357905851D",
    )

    decision = derive_pricing_admission(
        _prepared_with_matrix(
            matrix,
            category="other",
            oe_status="VERIFIED_EXACT",
            verified_cross=False,
        ),
        _identity_match(ComparabilityMatchLevel.EXACT),
    )

    assert decision.status is PricingAdmission.ADMITTED


def test_exact_oe_candidate_only_package_component_stays_manual() -> None:
    matrix = _matrix(
        "Колодки тормозные VW Golf 1K0698151",
        "Колодки тормозные VW Golf 1K0698151 с датчиком износа",
    )

    decision = derive_pricing_admission(
        _prepared_with_matrix(
            matrix,
            category="other",
            oe_status="VERIFIED_EXACT",
            verified_cross=False,
        ),
        _identity_match(ComparabilityMatchLevel.EXACT),
    )

    assert decision.status is PricingAdmission.MANUAL_REVIEW
    assert decision.reason_codes == (
        "PRICING_EVIDENCE_MISSING_INCLUDED_COMPONENTS",
    )


def test_exact_oe_candidate_only_sellable_subtype_stays_manual() -> None:
    matrix = _matrix(
        "Замок зажигания VW Golf 357905851D",
        "Контактная группа замка зажигания VW Golf 357905851D",
    )

    decision = derive_pricing_admission(
        _prepared_with_matrix(
            matrix,
            category="other",
            oe_status="VERIFIED_EXACT",
            verified_cross=False,
        ),
        _identity_match(ComparabilityMatchLevel.EXACT),
    )

    assert decision.status is PricingAdmission.MANUAL_REVIEW
    assert decision.reason_codes == (
        "PRICING_EVIDENCE_MISSING_ASSEMBLY_LEVEL",
        "PRICING_EVIDENCE_MISSING_PART_SUBTYPE",
    )


def test_ignition_lock_insert_wording_is_not_generic_assembly_match() -> None:
    matrix = _matrix(
        "Замок зажигания Renault Kangoo II 487002147R",
        "Вкладка замка запалювання Renault Kangoo 487002147R",
    )

    assert matrix["candidate"]["part_subtype"]["values"] == ["lock_cylinder"]
    assert matrix["candidate"]["assembly_level"]["values"] == ["component"]
    assert matrix["comparisons"]["part_subtype"]["state"] == "UNKNOWN"
    assert matrix["comparisons"]["assembly_level"]["state"] == "UNKNOWN"

    decision = derive_pricing_admission(
        _prepared_with_matrix(
            matrix,
            category="ignition_lock",
            oe_status="VERIFIED_EXACT",
            verified_cross=False,
        ),
        _identity_match(ComparabilityMatchLevel.EXACT),
    )

    assert decision.status is PricingAdmission.MANUAL_REVIEW
    assert decision.reason_codes == (
        "PRICING_EVIDENCE_MISSING_ASSEMBLY_LEVEL",
        "PRICING_EVIDENCE_MISSING_PART_SUBTYPE",
    )


def test_variant_conflict_is_excluded_from_pricing_without_false_not_match() -> None:
    matrix = _matrix(
        "Радіатор Opel Omega B 2,0 95-00 АКПП AC- 538*371",
        "Радиатор Opel Omega B 2,0 95-00 мех.КПП AC- 532*377",
    )
    output = _hard_stop_output(matrix["hard_stop_conflicts"])

    admission = derive_pricing_admission(_prepared_with_matrix(matrix), output)

    assert output.identity_verdict is IdentityVerdict.MANUAL_REVIEW
    assert admission.status is PricingAdmission.EXCLUDED
    assert admission.reason_codes == ("HARD_STOP_TRANSMISSION_VARIANT",)


def test_fuel_filter_pressure_reaches_pricing_admission_fail_closed() -> None:
    missing_matrix = _matrix(
        "Фильтр топлива VW Audi 6.4bar",
        "Фільтр паливний VW Audi",
    )
    conflicting_matrix = _matrix(
        "Фильтр топлива VW Audi 6.4bar",
        "Фільтр паливний VW Audi 4 bar",
    )

    missing = derive_pricing_admission(
        _prepared_with_matrix(missing_matrix, category="fuel filter"),
        _identity_match(ComparabilityMatchLevel.ACCEPTABLE_ANALOGUE),
    )
    conflict_output = _hard_stop_output(conflicting_matrix["hard_stop_conflicts"])
    conflicting = derive_pricing_admission(
        _prepared_with_matrix(conflicting_matrix, category="fuel filter"),
        conflict_output,
    )

    assert missing.status is PricingAdmission.MANUAL_REVIEW
    assert missing.reason_codes == ("PRICING_EVIDENCE_MISSING_OPERATING_PRESSURE",)
    assert conflict_output.identity_verdict is IdentityVerdict.MANUAL_REVIEW
    assert conflicting.status is PricingAdmission.EXCLUDED
    assert conflicting.reason_codes == ("HARD_STOP_OPERATING_PRESSURE",)


def test_verified_cross_cannot_use_model_exact_to_bypass_analogue_requirements() -> (
    None
):
    matrix = _matrix(
        "Фильтр топлива VW Audi 6.4bar",
        "Фільтр паливний VW Audi",
    )
    prepared = _prepared_with_matrix(matrix, category="fuel filter")
    model_exact = _identity_match(ComparabilityMatchLevel.EXACT)

    effective_level = _effective_identity_match_level(prepared, model_exact)
    admission = derive_pricing_admission(prepared, model_exact)

    assert effective_level is ComparabilityMatchLevel.ACCEPTABLE_ANALOGUE
    assert admission.status is PricingAdmission.MANUAL_REVIEW
    assert admission.reason_codes == ("PRICING_EVIDENCE_MISSING_OPERATING_PRESSURE",)


def test_verified_cross_requires_seed_asserted_side_and_position_for_pricing() -> None:
    matrix = _matrix(
        "Наконечник рулевой тяги передний правый VW Polo",
        "Наконечник рулевой тяги VW Polo",
    )

    admission = derive_pricing_admission(
        _prepared_with_matrix(matrix, category="steering"),
        _identity_match(ComparabilityMatchLevel.ACCEPTABLE_ANALOGUE),
    )

    assert admission.status is PricingAdmission.MANUAL_REVIEW
    assert admission.reason_codes == (
        "PRICING_EVIDENCE_MISSING_POSITION",
        "PRICING_EVIDENCE_MISSING_SIDE",
    )


def test_verified_cross_shock_absorber_requires_side_and_position() -> None:
    matrix = _matrix(
        "Амортизатор задній правий Toyota Camry V40",
        "Амортизатор Toyota Camry V40",
    )

    decision = derive_pricing_admission(
        _prepared_with_matrix(matrix, category="shock_absorber"),
        _identity_match(ComparabilityMatchLevel.ACCEPTABLE_ANALOGUE),
    )

    assert decision.status is PricingAdmission.MANUAL_REVIEW
    assert set(decision.reason_codes) >= {
        "PRICING_EVIDENCE_MISSING_POSITION",
        "PRICING_EVIDENCE_MISSING_SIDE",
    }


def test_legacy_cross_display_name_count_cannot_admit_pricing() -> None:
    matrix = _matrix(
        "Радіатор Iveco 625*440",
        "Радіатор Iveco Daily 625*440",
    )
    prepared = _prepared_with_matrix(matrix, category="radiator")
    snapshot = dict(prepared.input_snapshot)
    snapshot["candidate"] = {
        **snapshot["candidate"],
        "oe_verification_status": "VERIFIED_CROSS",
    }
    # This is the shape of a pre-hardening row: it claims two independent
    # sellers but has no durable-ID count.  It must remain manual.
    snapshot["verified_cross_edge"] = {
        "cross_link_id": "00000000-0000-0000-0000-000000000001",
        "seed_code": "SEED1",
        "candidate_code": "CANDIDATE1",
        "validation_status": "CONFIRMED",
        "independent_seller_count": 2,
    }
    decision = derive_pricing_admission(
        replace(prepared, input_snapshot=snapshot),
        _identity_match(ComparabilityMatchLevel.ACCEPTABLE_ANALOGUE),
    )

    assert decision.status is PricingAdmission.MANUAL_REVIEW
    assert decision.reason_codes == ("CROSS_EDGE_INDEPENDENCE_UNVERIFIED",)


@pytest.mark.parametrize(
    ("edge_patch", "expected_reason"),
    (
        ({"validation_status": "REVIEW"}, "CROSS_EDGE_UNVERIFIED"),
        ({"cross_link_id": ""}, "CROSS_EDGE_UNVERIFIED"),
        ({"seed_code": "OTHER-SEED"}, "CROSS_EDGE_BINDING_MISMATCH"),
        ({"candidate_code": "OTHER-CANDIDATE"}, "CROSS_EDGE_BINDING_MISMATCH"),
    ),
)
def test_cross_edge_status_and_codes_are_bound_before_pricing(
    edge_patch: dict[str, object],
    expected_reason: str,
) -> None:
    matrix = _matrix(
        "Радіатор Iveco 625*440",
        "Радіатор Iveco Daily 625*440",
    )
    prepared = _prepared_with_matrix(matrix, category="radiator")
    snapshot = dict(prepared.input_snapshot)
    edge = dict(snapshot["verified_cross_edge"])
    edge.update(edge_patch)
    snapshot["verified_cross_edge"] = edge

    decision = derive_pricing_admission(
        replace(prepared, input_snapshot=snapshot),
        _identity_match(ComparabilityMatchLevel.ACCEPTABLE_ANALOGUE),
    )

    assert decision.status is PricingAdmission.MANUAL_REVIEW
    assert decision.reason_codes == (expected_reason,)


def test_explicit_title_part_type_outranks_broad_category() -> None:
    matrix = build_semantic_feature_matrix(
        {
            "title": "Ролик паразитний ремня ГРМ Audi A4 31*59*8",
            "category": "1,4 Подшипники / Ступицы",
        },
        {"title": "Ролик ременя ГРМ Audi A4"},
    )

    assert matrix["our_product"]["part_family"]["values"] == ["belt_drive"]
    assert matrix["our_product"]["part_subtype"]["values"] == ["timing_roller"]
    assert matrix["our_product"]["part_family"]["evidence"][0]["source_field"] == (
        "title"
    )
    assert matrix["hard_stop_conflicts"] == []


def test_exact_code_only_bearing_is_not_an_engine_mount() -> None:
    matrix = _matrix(
        "Подушка двигателя Peugeot Partner",
        "Підшипник 180904",
    )

    assert matrix["candidate"]["part_subtype"]["values"] == ["generic_bearing"]
    assert "part_type" in {row["dimension"] for row in matrix["hard_stop_conflicts"]}


def test_stabilizer_link_with_position_adjective_is_recognized() -> None:
    matrix = _matrix(
        "Радиатор Peugeot 806 2.0 HDI",
        "Стійка переднього стабілізатора ліва Mazda 626",
    )

    assert matrix["candidate"]["part_subtype"]["values"] == ["stabilizer_link"]
    assert "part_type" in {row["dimension"] for row in matrix["hard_stop_conflicts"]}


def test_stabilizer_bracket_is_not_a_stabilizer_link() -> None:
    matrix = _matrix(
        "Стойка стабилизатора заднего Mercedes Sprinter",
        "Кронштейн стабілізатора заднього Mercedes Sprinter",
    )

    assert matrix["candidate"]["part_subtype"]["values"] == ["stabilizer_bracket"]
    assert "part_subtype" in {row["dimension"] for row in matrix["hard_stop_conflicts"]}


def test_steering_repair_kit_without_rack_word_is_not_complete_rack() -> None:
    matrix = _matrix(
        "Рейка рулевая Mercedes Sprinter с Г/У",
        "FREY 9014604100 Ремкомплект кермового Mercedes Sprinter",
    )

    assert matrix["candidate"]["part_subtype"]["values"] == ["steering_rack_repair_kit"]
    assert {row["dimension"] for row in matrix["hard_stop_conflicts"]} >= {
        "part_subtype",
        "assembly_level",
    }


def test_transmission_oil_cooler_language_variants_match() -> None:
    matrix = _matrix(
        "Радиатор масляный VW Golf 5 (AKП 6 ступ.)",
        "Масляный охладитель АКПП VW Golf 09G409061E",
    )

    assert matrix["comparisons"]["part_type"]["state"] == "MATCH"
    assert matrix["comparisons"]["part_subtype"]["state"] == "MATCH"
    assert matrix["hard_stop_conflicts"] == []


@pytest.mark.parametrize(
    ("seed_title", "candidate_title", "expected_subtype"),
    (
        (
            "Ручка стеклоподъемника Mercedes Sprinter",
            "Ручка ск/підймача VW T4",
            "window_crank_handle",
        ),
        (
            "Крестовина кардана Mercedes Vario 31x110",
            "Хрестовина BSG GU-3111 Mercedes Vario 31x110",
            "universal_joint",
        ),
        (
            "Пыльник рулевой рейки VW T4",
            "Пиловик рульової рейки VW Transporter",
            "steering_rack_boot",
        ),
        (
            "Патрубок радиатора верхний Mercedes Sprinter",
            "Патрубок радіатора A9015012782",
            "radiator_hose",
        ),
        (
            "Поршень VW Audi 1.8 STD",
            "Поршня KOLBENSCHMIDT 93928600",
            "engine_piston",
        ),
        (
            "Втулка кулисы КПП Ford Transit",
            "Втулка куліси Ford Transit 1334993",
            "shifter_bushing",
        ),
        (
            "Скоба замка дверей Fiat Ducato",
            "Фіксатор замка дверей Fiat Ducato",
            "lock_striker",
        ),
        (
            "Трос сцепления VW Golf 2",
            "Трос зчеплення VW Jetta 2",
            "clutch_cable",
        ),
        (
            "Бегунок трамблера VW Golf",
            "Бігунок трамблера Audi 80",
            "distributor_rotor",
        ),
        (
            "Резинка крепления глушителя Opel Omega",
            "Кронштейн глушника Opel Omega",
            "exhaust_hanger",
        ),
        (
            "Сальник клапана Daewoo Lanos",
            "Сальник клапанів Lanos 1.5",
            "valve_stem_seal",
        ),
        (
            "Шаровая опора Renault Master",
            "Опора кульова Opel Movano",
            "ball_joint",
        ),
        (
            "Шрус трешип Ford Focus",
            "Тришип Focus XS4C3W007AA",
            "tripod_joint",
        ),
        (
            "Корзина сцепления Opel Astra",
            "Кошик зчеплення Opel Astra",
            "clutch_pressure_plate",
        ),
        (
            "Замок багажника VW T5",
            "Замок кришки багажника VW T5",
            "trunk_lock",
        ),
        (
            "Рейка рулевая Audi A6",
            "Рульова рейка Audi A6",
            "steering_rack",
        ),
        (
            "Наконечник рулевой тяги Mercedes Vito",
            "Наконечник кермовий Mercedes Vito",
            "tie_rod_end",
        ),
        (
            "Вентилятор охлаждения двигателя Audi A4",
            "Вентилятор охолодження Audi A4",
            "engine_cooling_fan",
        ),
        (
            "Радиатор кондиционера Mercedes S221",
            "Конденсор кондиціонера Mercedes S221",
            "ac_condenser",
        ),
        (
            "Мотор печки Mercedes W211",
            "Вентилятор обігрівача Mercedes W211",
            "cabin_blower",
        ),
        (
            "Шланг тормозной VW T4",
            "Гальмівний шланг VW T4",
            "brake_hose",
        ),
        (
            "Фільтр повітря Audi A4",
            "Повітряний фільтр Audi A4",
            "engine_air_filter",
        ),
        (
            "Фильтр маслянный Ford",
            "Оливний фільтр Ford",
            "oil_filter",
        ),
        (
            "Прокладка випускного колектора VW",
            "Прокладка колектора випускного VW",
            "exhaust_manifold_gasket",
        ),
        (
            "Цилиндр сцепления рабочий VW Golf",
            "Робочий циліндр зчеплення VW Golf",
            "clutch_slave_cylinder",
        ),
        (
            "Датчик ABS VW Passat",
            "Датчик АБС VW Passat",
            "abs_sensor",
        ),
        (
            "Ст/подъемник электро передний VW T5",
            "Електричний склопідіймач передньої правої двері VW T5",
            "window_regulator",
        ),
        (
            "Мотор переднего стеклоочистителя VW T5",
            "Мотор передніх склоочисників VW T5",
            "wiper_motor",
        ),
        (
            "Зеркало VW T4 электрическое R",
            "Дзеркало VW T4 праве електричне",
            "mirror_assembly",
        ),
        (
            "Подушка верх.опорна Peugeot Boxer",
            "Подушка верхня опорна Fiat Ducato",
            "top_mount",
        ),
        (
            "Подушка двигат. Audi 80",
            "Подушка двигуна Audi 80",
            "engine_or_transmission_mount",
        ),
        (
            "Фланш головки VW Audi",
            "Фланець блока VW Audi",
            "coolant_sensor_flange",
        ),
        (
            "Решотка бампера нижняя Audi A6",
            "Решітка бампера нижня Audi A6",
            "bumper_grille",
        ),
        (
            "Клик зад. бампера VW T4 правий",
            "Ікло заднього бампера праве VW T4",
            "bumper_corner",
        ),
        (
            "Термомуфта Mercedes W124",
            "Віскомуфта вентилятора Mercedes W124",
            "fan_clutch",
        ),
        (
            "Патрубок вентиляции картера Mercedes",
            "Трубка сапуна Mercedes",
            "breather_hose",
        ),
        (
            "Подшипник конический 30204F 47*20*15",
            "Підшипник 30204 F 20*47*15",
            "generic_bearing",
        ),
        (
            "Ролик натяжения VW 1.9 TDI",
            "Ролик натягувача VW 1.9 TDI",
            "tensioner_roller",
        ),
        (
            "Шків генератора VW T5",
            "Шкив генератора VW T5",
            "alternator_pulley",
        ),
        (
            "Генератор VW Passat B5 120A",
            "Alternator VW Passat B5 120A",
            "alternator_assembly",
        ),
        (
            "Вкладыш передний аморт Opel Astra",
            "Вкладиш передній аморт Opel Astra",
            "strut_insert",
        ),
    ),
)
def test_additional_saved_market_taxonomy_is_bilingual_and_stable(
    seed_title: str,
    candidate_title: str,
    expected_subtype: str,
) -> None:
    matrix = _matrix(seed_title, candidate_title)

    assert matrix["our_product"]["part_subtype"]["values"] == [expected_subtype]
    assert matrix["candidate"]["part_subtype"]["values"] == [expected_subtype]
    assert matrix["hard_stop_conflicts"] == []


def test_sliding_door_guide_variants_prove_family_without_guessing_component() -> None:
    matrix = _matrix(
        "Направляющая сдвижной двери Fiat Ducato",
        "Напрямні бічні зсувні двері Fiat Ducato",
    )

    assert matrix["our_product"]["part_family"]["values"] == ["door_hardware"]
    assert matrix["candidate"]["part_family"]["values"] == ["door_hardware"]
    assert matrix["our_product"]["part_subtype"]["state"] == "UNKNOWN"
    assert matrix["hard_stop_conflicts"] == []


def test_drum_brake_kit_and_adjuster_are_different_sellable_packages() -> None:
    matrix = _matrix(
        "Ремкомплект заднего тормозного барабана Lanos R",
        "Механізм розвідний колодок Lanos правий",
    )

    assert matrix["our_product"]["part_family"]["values"] == ["drum_brake_hardware"]
    assert matrix["candidate"]["part_family"]["values"] == ["drum_brake_hardware"]
    assert matrix["our_product"]["part_subtype"]["values"] == [
        "drum_brake_repair_kit"
    ]
    assert matrix["candidate"]["part_subtype"]["values"] == [
        "drum_brake_adjuster"
    ]
    assert {item["dimension"] for item in matrix["hard_stop_conflicts"]} >= {
        "part_subtype",
        "assembly_level",
    }


def test_drum_brake_repair_kits_remain_comparable_to_each_other() -> None:
    matrix = _matrix(
        "Ремкомплект заднего тормозного барабана Lanos",
        "Рем комплект задніх гальмівних колодок Lanos повний",
    )

    assert matrix["comparisons"]["part_subtype"]["state"] == "MATCH"
    assert matrix["comparisons"]["assembly_level"]["state"] == "MATCH"
    assert matrix["hard_stop_conflicts"] == []


@pytest.mark.parametrize(
    ("complete_title", "component_title", "expected_dimension"),
    (
        ("Зеркало VW T4 правое", "Вкладыш в зеркало VW T4", "part_subtype"),
        ("Генератор VW T5", "Шкив генератора VW T5", "part_type"),
        ("Термомуфта Mercedes W124", "Крыльчатка термомуфты W124", "part_subtype"),
    ),
)
def test_new_v7_components_do_not_merge_with_adjacent_assemblies(
    complete_title: str,
    component_title: str,
    expected_dimension: str,
) -> None:
    matrix = _matrix(complete_title, component_title)

    assert expected_dimension in {
        conflict["dimension"] for conflict in matrix["hard_stop_conflicts"]
    }


@pytest.mark.parametrize(
    ("seed_title", "candidate_title", "expected_family", "expected_subtype"),
    (
        (
            "Крышка трамблера Audi 100",
            "Кришка трамблера Audi 100",
            "ignition_system",
            "distributor_cap",
        ),
        (
            "Коммутатор VW Golf 2",
            "Комутатор VW Golf 2",
            "ignition_system",
            "ignition_module",
        ),
        (
            "Распредвал VW T4 2.5 TDI",
            "Camshaft VW T4 2.5 TDI",
            "engine_internal",
            "camshaft",
        ),
        (
            "Клапан выпускной VW 1.8",
            "Клапан випускний VW 1.8",
            "engine_internal",
            "engine_valve",
        ),
        (
            "Гидрокомпенсатор VW Audi",
            "Гідрокомпенсатор VW Audi",
            "engine_internal",
            "hydraulic_lifter",
        ),
        (
            "Поддон VW Golf 1.8",
            "Oil pan VW Golf 1.8",
            "engine_lubrication",
            "oil_pan",
        ),
        (
            "Сальник коленвала VW T5",
            "Сальник колінвала VW T5",
            "oil_seal",
            "crankshaft_oil_seal",
        ),
        (
            "Насос омывателя VW T5",
            "Washer pump VW T5",
            "washer_system",
            "washer_pump",
        ),
        (
            "Отбойник амортизатора VW Passat",
            "Відбійник амортизатора VW Passat",
            "suspension",
            "bump_stop",
        ),
        (
            "Пыльник амортизатора Ford Focus",
            "Пильник стійки Ford Focus",
            "suspension",
            "strut_boot",
        ),
        (
            "Подшипник верхний опорный Ford Transit",
            "Підшипник верхній опорний Ford Transit",
            "suspension",
            "top_mount_bearing",
        ),
        (
            "Противотуманка VW T5",
            "Fog lamp VW T5",
            "vehicle_lighting",
            "fog_lamp",
        ),
        (
            "Стекло фары VW Passat",
            "Headlamp lens VW Passat",
            "vehicle_lighting",
            "headlamp_lens",
        ),
        (
            "Фара Mercedes Sprinter",
            "Headlamp Mercedes Sprinter",
            "vehicle_lighting",
            "headlamp",
        ),
        (
            "Указатель поворота VW LT",
            "Turn signal lamp VW LT",
            "vehicle_lighting",
            "turn_signal_lamp",
        ),
        (
            "Фонарь задний Ford Transit",
            "Ліхтар задній Ford Transit",
            "vehicle_lighting",
            "rear_or_marker_lamp",
        ),
        (
            "Молдинг Audi A6",
            "Молдінг Audi A6",
            "body_trim",
            "moulding",
        ),
        (
            "Значок решетки VW Golf",
            "Емблема решітки VW Golf",
            "body_trim",
            "emblem",
        ),
        (
            "Генератор щеточный узел Daewoo Lanos",
            "Генератор щітковий вузол Daewoo Lanos",
            "electrical_charging",
            "alternator_brush_holder",
        ),
        (
            "Свеча накала Mercedes Sprinter",
            "Свічка розжарювання Mercedes Sprinter",
            "ignition_system",
            "glow_plug",
        ),
        (
            "Прокладка корпуса масляного фильтра VW",
            "Прокладка корпусу масляного фільтра VW",
            "gasket",
            "oil_filter_housing_gasket",
        ),
        (
            "Подшипник ступеци передней VW Polo",
            "Підшипник маточини передньої VW Polo",
            "wheel_end",
            "wheel_bearing",
        ),
    ),
)
def test_v7_closed_noun_taxonomy_is_bilingual_and_stable(
    seed_title: str,
    candidate_title: str,
    expected_family: str,
    expected_subtype: str,
) -> None:
    matrix = _matrix(seed_title, candidate_title)

    assert matrix["our_product"]["part_family"]["values"] == [expected_family]
    assert matrix["candidate"]["part_family"]["values"] == [expected_family]
    assert matrix["our_product"]["part_subtype"]["values"] == [expected_subtype]
    assert matrix["candidate"]["part_subtype"]["values"] == [expected_subtype]
    assert matrix["hard_stop_conflicts"] == []


@pytest.mark.parametrize(
    ("title", "expected_family"),
    (
        ("Датчик сигнальной лампы охлаждающей жидкости VW", "sensor"),
        ("Прокладка АКПП Opel Omega", "gasket"),
        ("Сайлентблок VW Audi", "suspension"),
        ("Колодки задние Renault Trafic", "brake_friction"),
    ),
)
def test_v7_generic_closed_nouns_prove_only_family(
    title: str,
    expected_family: str,
) -> None:
    features = extract_semantic_features({"title": title})

    assert features["part_family"].values == (expected_family,)
    assert features["part_subtype"].values in ((), ("brake_pad",))


@pytest.mark.parametrize(
    ("left", "right", "dimension"),
    (
        (
            "Подшипник передней ступицы Mercedes W203",
            "Подшипник 6006 30x55x13",
            "part_type",
        ),
        (
            "Амортизатор передний Daewoo Lanos",
            "Вкладыш передний аморт Daewoo Lanos",
            "part_subtype",
        ),
    ),
)
def test_v7_catalogue_language_overlap_is_unknown_not_false_conflict(
    left: str,
    right: str,
    dimension: str,
) -> None:
    matrix = _matrix(left, right)

    assert matrix["comparisons"][dimension]["state"] == "UNKNOWN"
    assert dimension not in {
        conflict["dimension"] for conflict in matrix["hard_stop_conflicts"]
    }


@pytest.mark.parametrize(
    ("title", "expected_family", "expected_subtype"),
    (
        ("Замок капота VW T5", "door_lock", "hood_latch"),
        ("Замок бардачка VW Golf 3", "interior_hardware", "glovebox_lock"),
        ("Замок (защелка) двери VW Passat", "door_lock", "door_lock"),
        ("Ручка Opel Astra передняя L", "door_hardware", "door_handle"),
        (
            "Лічинка замка запалювання Audi 100",
            "ignition_lock",
            "lock_cylinder",
        ),
        ("Трос газа Daewoo Lanos", "throttle_control", "throttle_cable"),
        ("Тросс капота VW Golf", "hood_release", "hood_release_cable"),
        ("Трос спидометра VW Passat", "instrumentation", "speedometer_cable"),
        ("Трос ручника VW Golf", "parking_brake", "parking_brake_cable"),
        ("Кнопка аварійки Opel Astra", "electrical_switch", "hazard_switch"),
        ("Перемикач світла Mercedes", "electrical_switch", "light_switch"),
        (
            "Джойстик керування дзеркалами Mercedes",
            "mirror_controls",
            "mirror_adjustment_switch",
        ),
        (
            "Переключатель ст/очист Audi 100",
            "steering_column_switch",
            "wiper_switch",
        ),
        ("Ролик генератора Ford Transit", "belt_drive", "alternator_roller"),
        (
            "Механізм натяжки ремня генератора Mercedes",
            "belt_drive",
            "tensioner_assembly",
        ),
        ("Ремінь клиновидний 10x730", "belt_drive", "v_belt"),
        ("Подушка карбюратора Audi 80", "intake_mount", "carburetor_mount"),
        ("Подушка задньої балки Mercedes", "suspension", "axle_beam_mount"),
        (
            "Кронштейн крепления бампера Audi 100",
            "body_mounting",
            "bumper_bracket",
        ),
        ("Петля капота Daewoo Lanos", "body_hinge", "hood_hinge"),
        ("Петля задньої двері Mercedes", "body_hinge", "door_hinge"),
        (
            "Патрубок интеркулера Mercedes Sprinter",
            "charge_air_hose",
            "intercooler_hose",
        ),
        ("Шестерня коленвала Daewoo", "engine_timing", "crankshaft_gear"),
        ("Шестерня 5-й передачи Chery", "transmission", "fifth_gear"),
        (
            "Карданчик рулевой рейки VW Golf",
            "steering",
            "steering_column_joint",
        ),
        ("Кулак поворотный Chery Amulet", "suspension", "steering_knuckle"),
        ("Лист ресори задньої Ford Transit", "suspension", "leaf_spring"),
    ),
)
def test_v7_customer_catalogue_components_have_stable_taxonomy(
    title: str,
    expected_family: str,
    expected_subtype: str,
) -> None:
    features = extract_semantic_features({"title": title})

    assert features["part_family"].values == (expected_family,)
    assert features["part_subtype"].values == (expected_subtype,)


@pytest.mark.parametrize(
    ("title", "expected_family", "expected_subtype"),
    (
        (
            "Крышка масла заливной горловины Opel Astra",
            "engine_lubrication",
            "oil_filler_cap",
        ),
        ("Кришка бензобака Ford Transit", "fuel_system", "fuel_tank_cap"),
        (
            "Пласмаска щупа VW Passat B5 1.9 TDI",
            "engine_lubrication",
            "dipstick_guide",
        ),
        (
            "Щуп уровня масла Renault Trafic",
            "engine_lubrication",
            "oil_dipstick",
        ),
        (
            "Натяжитель цепи ГРМ Audi A4 1.8 T",
            "timing_chain_drive",
            "timing_chain_tensioner",
        ),
        (
            "Заспокоювач ланцюга Mercedes OM 601",
            "timing_chain_drive",
            "timing_chain_guide",
        ),
        ("Шкив коленвала Ford Transit", "belt_drive", "crankshaft_pulley"),
        ("Щетки дворников VW Audi 450 mm", "wiper_system", "wiper_blade"),
        ("Опір печі Mercedes Vito", "hvac", "blower_resistor"),
        ("Мотор печі Renault Master", "hvac", "cabin_blower"),
        ("Корзина зчеплення Opel Astra", "clutch", "clutch_pressure_plate"),
        ("Шаровая оппора Mercedes Sprinter", "suspension_joint", "ball_joint"),
        ("Витратомір повітря Mercedes Vito", "sensor", "mass_air_flow_sensor"),
        ("Клапан холостого хода Audi 100", "air_intake", "idle_air_control_valve"),
        (
            "Вкладыши разбега колленвала Ford OHC",
            "engine_bearing",
            "crankshaft_thrust_washer",
        ),
        ("Вкладыши распредвала Ford OHC", "engine_bearing", "camshaft_bearing"),
        ("Коромисло Ford Transit 2.5D", "engine_internal", "rocker_arm"),
        (
            "Тяжка выбора передачь КПП VW Golf 2",
            "transmission_controls",
            "shift_linkage_rod",
        ),
        ("Ексцентрик замка двері VW Polo", "door_lock", "lock_eccentric"),
    ),
)
def test_v8_residual_customer_terms_have_precise_taxonomy(
    title: str,
    expected_family: str,
    expected_subtype: str,
) -> None:
    features = extract_semantic_features({"title": title})

    assert features["part_family"].values == (expected_family,)
    assert features["part_subtype"].values == (expected_subtype,)


@pytest.mark.parametrize(
    ("left", "right", "expected_dimension"),
    (
        (
            "Крышка масла заливной горловины Opel",
            "Крышка бензобака Opel",
            "part_type",
        ),
        (
            "Натяжитель цепи ГРМ Audi",
            "Успокоитель цепи ГРМ Audi",
            "part_subtype",
        ),
        ("Мотор печи Renault", "Опір печі Renault", "part_subtype"),
        ("Щетка дворника VW", "Переключатель стеклоочистителя VW", "part_type"),
        (
            "Тяга выбора передач КПП VW",
            "Вилка переключения КПП VW",
            "part_type",
        ),
        ("Вкладыши разбега коленвала Ford", "Вкладыши коренные Ford", "part_subtype"),
    ),
)
def test_v8_adjacent_components_are_hard_stopped(
    left: str,
    right: str,
    expected_dimension: str,
) -> None:
    matrix = _matrix(left, right)

    assert expected_dimension in {
        conflict["dimension"] for conflict in matrix["hard_stop_conflicts"]
    }


@pytest.mark.parametrize(
    ("title", "expected_family", "expected_subtype"),
    (
        ("Барабан тормозной Daewoo Lanos", "brake_drum", "brake_drum"),
        ("Бігун трамблера Ford Sierra", "ignition_system", "distributor_rotor"),
        ("Вимикач концевик двері Duster", "electrical_switch", "door_jamb_switch"),
        ("Кнопка педали тормоза VW T5", "electrical_switch", "brake_light_switch"),
        ("Брызговик задний Mercedes Sprinter", "body_protection", "mud_flap"),
        ("Вакуум трамблера VW Golf", "ignition_system", "distributor_vacuum_advance"),
        ("Венец маховика Mercedes OM602", "flywheel", "flywheel_ring_gear"),
        ("Маховик Chery Amulet", "flywheel", "flywheel"),
        ("Вилка выжима сцепления VW", "clutch_control", "clutch_fork"),
        (
            "Діодний міст генератора Daewoo",
            "electrical_charging",
            "alternator_rectifier",
        ),
        (
            "Релле генератора Ford Transit",
            "electrical_charging",
            "alternator_regulator",
        ),
        ("Защита ГРМ VW Passat", "engine_timing", "timing_cover"),
        ("Звезда вала коленчатого VW", "engine_timing", "crankshaft_sprocket"),
        ("Звездочка распредвала Mercedes", "engine_timing", "camshaft_sprocket"),
        ("Карбюратор Pierburg VW Audi", "fuel_system", "carburetor"),
        ("Ремкомплект карбюратора Ford", "fuel_system", "carburetor_repair_kit"),
        ("Лампа накаливания H7 12V 100W", "vehicle_lighting", "bulb"),
        ("Крышка бачка омывателя VW", "washer_system", "washer_reservoir_cap"),
        ("Крышка распределителя зажигания MB", "ignition_system", "distributor_cap"),
        (
            "Ручка сувальної двері Renault Master",
            "door_hardware",
            "sliding_door_handle",
        ),
        ("Ролик дверей ковзаючих Mercedes", "door_hardware", "sliding_door_roller"),
        ("Кронштейн сувальної двері Renault", "door_hardware", "sliding_door_bracket"),
        ("Подушка коробки Ford Mondeo", "engine_mount", "transmission_mount"),
        (
            "Муфта еластичная кардана Mercedes",
            "driveline",
            "propshaft_flexible_coupling",
        ),
        ("Кнопка стеклопідйомника Audi", "window_controls", "window_switch"),
        ("Перемикач ск/очист VW", "steering_column_switch", "wiper_switch"),
        ("Вмикач світла VW Caddy", "electrical_switch", "light_switch"),
        ("Вкладиш корен. Opel 1.3", "engine_bearing", "main_bearing"),
        ("Ремень зубчатый газораспр VW Audi", "belt_drive", "timing_belt"),
        ("Пробка зливу масла Daewoo", "engine_lubrication", "oil_drain_plug"),
        ("Кришка,заливна горловина масла Ford", "engine_lubrication", "oil_filler_cap"),
    ),
)
def test_v9_residual_customer_terms_have_precise_taxonomy(
    title: str,
    expected_family: str,
    expected_subtype: str,
) -> None:
    features = extract_semantic_features({"title": title})

    assert features["part_family"].values == (expected_family,)
    assert features["part_subtype"].values == (expected_subtype,)


@pytest.mark.parametrize(
    ("left", "right", "expected_dimension"),
    (
        ("Барабан тормозной VW", "Диск тормозной VW", "part_type"),
        ("Бігун трамблера Ford", "Крышка трамблера Ford", "part_subtype"),
        ("Концевик двери VW", "Кнопка педали тормоза VW", "part_subtype"),
        ("Маховик Mercedes", "Венец маховика Mercedes", "part_subtype"),
        ("Діодний міст генератора Ford", "Реле генератора Ford", "part_subtype"),
        ("Защита ГРМ Audi", "Ремень зубчатый ГРМ Audi", "part_type"),
        ("Звезда коленчатого вала VW", "Звездочка распредвала VW", "part_subtype"),
        ("Карбюратор Ford", "Ремкомплект карбюратора Ford", "part_subtype"),
        ("Лампа H7 12V", "Свеча накала Mercedes", "part_type"),
        ("Бачок омывателя VW", "Крышка бачка омывателя VW", "part_subtype"),
        (
            "Ручка сувальной двери Renault",
            "Ролик двери сдвижной Renault",
            "part_subtype",
        ),
        ("Подушка коробки Ford", "Подушка двигателя Ford", "part_subtype"),
        ("Пробка злива масла Opel", "Крышка залива масла Opel", "part_subtype"),
    ),
)
def test_v9_adjacent_components_are_hard_stopped(
    left: str,
    right: str,
    expected_dimension: str,
) -> None:
    matrix = _matrix(left, right)

    assert expected_dimension in {
        conflict["dimension"] for conflict in matrix["hard_stop_conflicts"]
    }


def test_v9_sliding_door_bracket_revision_wording_is_equivalent() -> None:
    matrix = _matrix(
        "Кронштейн сдвижной двери Renault Trafic (ремкомплект ролики)",
        "Кронштейн сувальної двері Renault Trafic (ремкомплект ролики)",
    )

    assert matrix["our_product"]["part_subtype"]["values"] == ["sliding_door_bracket"]
    assert matrix["candidate"]["part_subtype"]["values"] == ["sliding_door_bracket"]
    assert matrix["hard_stop_conflicts"] == []


def test_v9_sliding_door_bracket_and_roller_wording_is_not_identity_disproof() -> None:
    matrix = _matrix(
        "Кронштейн сдвижной двери Renault",
        "Ролик сдвижной двери Renault",
    )

    assert matrix["comparisons"]["part_subtype"]["state"] == "UNKNOWN"
    assert not {
        "part_subtype",
        "assembly_level",
    } & {conflict["dimension"] for conflict in matrix["hard_stop_conflicts"]}


def test_v9_roller_of_sliding_door_bracket_stays_a_roller() -> None:
    features = extract_semantic_features(
        {"title": ("Ролик кронштейна сдвижной двери Renault Trafic верхний")}
    )

    assert features["part_subtype"].values == ("sliding_door_roller",)


@pytest.mark.parametrize(
    ("title", "expected_family", "expected_subtype"),
    (
        ("Подшипник КПП VW Golf", "transmission", "gearbox_bearing"),
        (
            "Ручка регулятора спинки сидения VW",
            "seat_hardware",
            "seat_back_adjuster_handle",
        ),
        ("Ручка открывания капота Ford", "hood_release", "hood_release_handle"),
        ("Кронштейн ручки капота VW", "hood_release", "hood_handle_bracket"),
        ("Ручка бардачка Opel", "interior_hardware", "glovebox_handle"),
        (
            "Шланг гидроусилителя руля Mercedes",
            "steering_hydraulics",
            "power_steering_hose",
        ),
        ("Коллектор выпускной Ford", "exhaust", "exhaust_manifold"),
        ("Успокоитель ремня ГРМ Audi", "belt_drive", "timing_belt_guide"),
        ("Направляющая клапана Ford", "engine_internal", "valve_guide"),
        ("Регулятор давления топлива VW", "fuel_system", "fuel_pressure_regulator"),
        (
            "Клапан вентиляции топливного бака Audi",
            "fuel_system",
            "fuel_tank_vent_valve",
        ),
        ("Промежуточный вал двигателя VW", "engine_internal", "intermediate_shaft"),
        (
            "Рамка крепления противотуманной фары VW",
            "vehicle_lighting",
            "fog_lamp_frame",
        ),
        ("Усилитель бампера VW", "body_structure", "bumper_reinforcement"),
        ("Накладка арки VW", "body_trim", "wheel_arch_trim"),
        ("Диск выключения сцепления VW", "clutch", "clutch_release_plate"),
        ("Педаль сцепления VW", "pedal_assembly", "clutch_pedal"),
        ("Педаль газа VW", "pedal_assembly", "accelerator_pedal"),
        ("Блок управления вентилятором VW", "cooling_electrical", "fan_control_module"),
        ("Блок управления светом VW", "lighting_controls", "lighting_control_module"),
        ("Приводной вал VW", "driveline", "drive_shaft"),
        ("Шестерня привода спидометра VW", "transmission", "speedometer_drive_gear"),
        ("Скоба глушителя VW", "exhaust_mount", "exhaust_clamp"),
        ("Кольцо глушителя VW", "exhaust_mount", "exhaust_sealing_ring"),
        ("Сепаратор обратки Ford", "fuel_system", "fuel_return_separator"),
        (
            "Подшипник коленвала игольчатый VW",
            "engine_bearing",
            "crankshaft_pilot_bearing",
        ),
        (
            "Подушка опорная кардана Mercedes",
            "driveline_bearing",
            "propshaft_support_cushion",
        ),
        ("Подушка стойки VW", "suspension", "strut_mount"),
        ("Пыльник рулевой тяги VW", "steering", "steering_rack_boot"),
        ("Трещотка сцепления Ford", "clutch_control", "clutch_ratchet"),
        ("Плата заднего фонаря VW", "vehicle_lighting", "rear_lamp_circuit_board"),
        ("Распределитель воды тройник VW", "cooling", "coolant_distribution_flange"),
        ("Кулиса КПП VW", "transmission_controls", "shifter_assembly"),
        ("Чехол кулисы КПП VW", "transmission_controls", "shifter_boot"),
        ("Глушилка двигателя дизель VW", "engine_control", "diesel_stop_actuator"),
        ("Наконечник рулевой VW", "steering", "tie_rod_end"),
        ("Стеклоподъемник VW", "window_regulator", "window_regulator"),
        ("Вентилятор основной VW", "cooling_fan", "engine_cooling_fan"),
        ("Разъем вентилятора VW", "electrical_connector", "fan_connector"),
        ("Предохранитель 20A VW", "electrical_protection", "fuse"),
        ("Решетка нижняя VW", "body_grille", "lower_grille"),
        ("Накладка под фару VW", "body_trim", "headlamp_trim"),
        ("Механизм натяжителя ремня VW", "belt_drive", "tensioner_assembly"),
    ),
)
def test_v10_residual_customer_terms_have_precise_taxonomy(
    title: str,
    expected_family: str,
    expected_subtype: str,
) -> None:
    features = extract_semantic_features({"title": title})

    assert features["part_family"].values == (expected_family,)
    assert features["part_subtype"].values == (expected_subtype,)


@pytest.mark.parametrize(
    ("left", "right", "expected_dimension"),
    (
        ("Подшипник КПП VW", "Подшипник коленвала игольчатый VW", "part_type"),
        ("Ручка открывания капота VW", "Ручка бардачка VW", "part_type"),
        (
            "Регулятор давления топлива VW",
            "Клапан вентиляции топливного бака VW",
            "part_subtype",
        ),
        ("Успокоитель ремня ГРМ Audi", "Успокоитель цепи ГРМ Audi", "part_type"),
        ("Диск выключения сцепления VW", "Диск сцепления VW", "part_subtype"),
        ("Блок управления вентилятором VW", "Разъем вентилятора VW", "part_type"),
        ("Шестерня спидометра VW", "Звезда коленчатого вала VW", "part_type"),
        ("Скоба глушителя VW", "Кольцо глушителя VW", "part_subtype"),
        ("Кулиса КПП VW", "Чехол кулисы КПП VW", "part_subtype"),
        ("Вентилятор основной VW", "Мотор печи VW", "part_type"),
    ),
)
def test_v10_adjacent_components_are_hard_stopped(
    left: str,
    right: str,
    expected_dimension: str,
) -> None:
    matrix = _matrix(left, right)

    assert expected_dimension in {
        conflict["dimension"] for conflict in matrix["hard_stop_conflicts"]
    }


def test_v10_timing_belt_guide_revision_wording_is_equivalent() -> None:
    matrix = _matrix(
        "Натяжитель-уcпокоитель ремня ГРМ Audi 1.8T",
        "Натяжник-успокійник ременя ГРМ Audi 1.8T",
    )

    assert matrix["our_product"]["part_subtype"]["values"] == ["timing_belt_guide"]
    assert matrix["candidate"]["part_subtype"]["values"] == ["timing_belt_guide"]
    assert matrix["hard_stop_conflicts"] == []


@pytest.mark.parametrize(
    ("title", "expected_subtype"),
    (
        ("Болт колесный VW", "wheel_bolt"),
        ("Болт колінвала Ford Transit", "crankshaft_bolt"),
        ("Болт крепления дверной петли Daewoo", "door_hinge_bolt"),
        ("Болт натяжки генератора VW", "alternator_tension_bolt"),
        ("Болт натяжного ролика VW", "tensioner_roller_bolt"),
        ("Комплект болтов ГБЦ Boxer", "cylinder_head_bolt_set"),
        ("Кронштейн перед двиг VW", "engine_mount_bracket"),
        ("Надпись Daewoo", "vehicle_badge"),
        ("Мотор вентилятор кондиционера Mercedes", "ac_condenser_fan"),
        ("Подушка передней рессоры Mercedes", "leaf_spring_pad"),
        ("Герметик 200ml Mercedes", "sealant"),
        ("Скоба двери MB Vario", "lock_striker"),
        ("Втулка рулевого вала Citroen", "steering_column_bushing"),
        ("Первичный вал КПП Chery", "input_shaft"),
        ("Накладка зеркала Chery", "mirror_cover"),
        ("Антена електрична універсальна", "electric_antenna"),
        ("Бендікс VW T4", "starter_components"),
        ("Вал трамблера Audi", "distributor_shaft"),
        ("Вкладыш пром.вала OHC", "intermediate_shaft_bearing"),
        ("Вставка заркала Renault", "mirror_glass"),
        ("Дворники комплект Mercedes", "wiper_blade"),
        ("Диск вимикання зчеплення VW", "clutch_release_plate"),
        ("Дополнительный стоп сигнал VW", "third_brake_light"),
        ("Заглушка переднего бампера Renault", "bumper_cover_cap"),
        ("Запальничка в зборі Daewoo", "cigarette_lighter"),
        ("Кільце глушника VW", "exhaust_sealing_ring"),
        ("Клапан EGR VW", "egr_valve"),
        ("Клапан управления турбиной Mercedes", "turbo_control_valve"),
        ("Кнопка відкривання багажника Renault", "trunk_release_switch"),
        ("Колпак колесного диска VW", "wheel_center_cap"),
        ("Комплект личинок замков Ford", "lock_cylinder_set"),
        ("Корпус подвесного подшипника Opel", "center_support_bearing_housing"),
        ("Кронштейн КПП Audi", "gearbox_bracket"),
        ("Крыльчатка 380мм Mercedes", "fan_impeller"),
        ("Крышка масляного фильтра Mercedes", "oil_filter_cap"),
        ("Личинка замка багажника VW", "trunk_lock_cylinder"),
        ("Мотор стеклопідйомника Daewoo", "window_regulator_motor"),
        ("Накладка панели приборов Mercedes", "dashboard_trim"),
        ("Направляюча бампера Chery", "bumper_bracket"),
        ("Насос рециркуляции антифриза VW", "coolant_recirculation_pump"),
        ("Обратный клапан омывателя Mercedes", "washer_check_valve"),
        ("Опорная чашка задней пружины Audi", "spring_seat"),
        ("Отражатель заднего бампера Renault", "bumper_reflector"),
        ("Палец натяжного ролика Mercedes", "tensioner_pivot_pin"),
        ("Патркбок печки Ford", "heater_hose"),
        ("Патрубок воздушный Ford", "intake_hose"),
        ("Петля буксировочная Sprinter", "tow_eye"),
        ("Пиловик амморт. VW", "shock_absorber_boot"),
        ("Плавающий сайлентблок Mercedes", "floating_bushing"),
        ("Повторитель поворота VW", "turn_signal_repeater"),
        ("Подсветка номера VW", "license_plate_lamp"),
        ("Привод стеклоочистителя трапеция Mercedes", "wiper_linkage"),
        ("Разъем АКПП Mercedes", "transmission_connector"),
        ("Ремень ручейковый Opel", "serpentine_belt"),
        ("Ремінь зубчастий VW", "timing_belt"),
        ("Ремкомплект важеля Mercedes", "control_arm_repair_kit"),
        ("Ремкомплект маятника Mercedes", "steering_idler_repair_kit"),
        ("Розподвал Ford", "camshaft"),
        ("Селектор перемикання АКПП VW", "automatic_transmission_selector"),
        ("Сепаратор паров бензина Chery", "fuel_vapor_separator"),
        ("Стекло заднего фонаря Mercedes", "tail_lamp_lens"),
        ("Толкатель клапана Mercedes", "valve_tappet"),
        ("Трубка змащення турбіни Peugeot", "turbo_oil_line"),
        ("Трубка ТНВД Mercedes", "injection_pump_line"),
        ("Тяга переднего стабилизатора VW", "stabilizer_link"),
        ("Тяжка КПП Mercedes", "shift_linkage_rod"),
        ("Уплотнитель передней двери VW", "door_weatherstrip"),
        ("Шкворень Mercedes", "kingpin"),
        ("Шланг обратки топлива VW", "fuel_return_hose"),
    ),
)
def test_v11_customer_terms_have_precise_taxonomy(
    title: str,
    expected_subtype: str,
) -> None:
    features = extract_semantic_features({"title": title})

    assert features["part_family"].values
    assert features["part_subtype"].values == (expected_subtype,)


@pytest.mark.parametrize(
    ("left", "right", "expected_dimension"),
    (
        ("Болт колесный VW", "Болт коленвала VW", "part_type"),
        ("Болт дверной петли Daewoo", "Болт натяжного ролика VW", "part_type"),
        ("Мотор кондиционера Mercedes", "Мотор радиатора Mercedes", "part_subtype"),
        ("Накладка зеркала Renault", "Вставка зеркала Renault", "part_subtype"),
        ("Дополнительный стоп сигнал VW", "Повторитель поворота VW", "part_subtype"),
        ("Крышка масляного фильтра VW", "Фильтр масляный VW", "part_subtype"),
        (
            "Обратный клапан омывателя Mercedes",
            "Насос омывателя Mercedes",
            "part_subtype",
        ),
        ("Опорная чашка задней пружины Audi", "Пружина задняя Audi", "part_subtype"),
        ("Патрубок печки Ford", "Патрубок воздушный Ford", "part_type"),
        ("Сальник МКП Mercedes", "Сальник распредвала Mercedes", "part_subtype"),
        ("Трубка ТНВД Mercedes", "Трубка змащення турбіни Mercedes", "part_type"),
    ),
)
def test_v11_adjacent_components_are_hard_stopped(
    left: str,
    right: str,
    expected_dimension: str,
) -> None:
    matrix = _matrix(left, right)

    assert expected_dimension in {
        conflict["dimension"] for conflict in matrix["hard_stop_conflicts"]
    }


@pytest.mark.parametrize(
    "title",
    (
        "Фланш задний 1.6-2.0 Audi VW",
        "Ролик ZETEC большой",
        "Ролик CVH 86-",
        "Шланг генератора бронированный Ford",
        "Демпфер Mercedes OM651",
        "Защита",
        "Кольцо КПП VW",
    ),
)
def test_v11_ambiguous_customer_terms_remain_unknown(title: str) -> None:
    features = extract_semantic_features({"title": title})

    assert features["part_family"].values == ()
    assert features["part_subtype"].values == ()


def test_v11_window_regulator_motor_abbreviation_is_equivalent() -> None:
    matrix = _matrix(
        "Мотор стеклоподъемника правый Daewoo Lanos",
        "Мотор ск/підймача правий Daewoo Lanos",
    )

    assert matrix["our_product"]["part_subtype"]["values"] == ["window_regulator_motor"]
    assert matrix["candidate"]["part_subtype"]["values"] == ["window_regulator_motor"]
    assert matrix["hard_stop_conflicts"] == []


_LIVE_TOP_MOUNT_BEARING_SEED = (
    "Подшипник верхний опорн VW (Фольксваген) Golf-5/А-2:3/ "
    "Skoda Оktav.Fab. Caddy3 Passat 03-"
)


@pytest.mark.parametrize(
    "candidate",
    (
        "1K0412249B Опорный подшипник переднего амортизатора Q3 8U 15-18",
        (
            "Підшипник верхньої опори 6N0412249C B18294 1K0412249B, "
            "6N0412249E, 6N0412249B, 6N0412249D BORSEHUNG 1.2-1,4 Фаб"
        ),
        "Подушка амортизатора з підшипником AUDI, SEAT, SKODA, VW 1K0412249B",
    ),
)
def test_live_top_mount_bearing_is_not_a_top_mount_or_an_absorber(
    candidate: str,
) -> None:
    """The 2026-08-05 live shadow lost these three to rule order, not to fact.

    ``top_mount``'s wording rule sits ahead of ``top_mount_bearing`` in
    ``_PART_PATTERNS``, and the first match wins, so "Опорный подшипник
    амортизатора" was read as a bare top mount. The same class of ordering
    defect was reported twice before (shadow-doc defects #2 and #9); these are
    real candidates for a real customer position, and all three are the part.
    """

    matrix = _matrix(_LIVE_TOP_MOUNT_BEARING_SEED, candidate)

    assert matrix["candidate"]["part_subtype"]["values"] == ["top_mount_bearing"]
    assert matrix["hard_stop_conflicts"] == []


def test_live_charge_air_radiator_is_an_intercooler() -> None:
    """``Радіатор наддуву`` is a charge-air cooler, not an engine radiator.

    The ``intercooler`` rule covers ``інтеркулер`` and ``охолоджувач
    наддувного повітря`` but not this wording, so the generic engine-radiator
    rule claimed it. Both sit on query ``0384J9 -> 0384N6``, which the shadow
    document itself lists as a successful intercooler cross.
    """

    matrix = _matrix(
        "Радиатор интеркулер  Peugeot (Пежо) 806 Expert, "
        " Fiat (Фіат) Scudo, Citroen Jumpy 07-",
        "Радіатор наддуву PEUGEOT 207 (06-) 1.6 HDI/ M /AC+/-(05/06-) OE 0384.N8 96594",
    )

    assert matrix["candidate"]["part_subtype"]["values"] == ["intercooler"]
    assert matrix["hard_stop_conflicts"] == []


def test_an_engine_cooling_radiator_is_still_not_an_intercooler() -> None:
    """The widening above must not erase the distinction it sits next to."""

    matrix = _matrix(
        "Радиатор интеркулер Peugeot 806 Expert",
        "Радіатор охолодження двигуна PEUGEOT 207 1.6 HDI",
    )

    assert matrix["candidate"]["part_subtype"]["values"] == [
        "engine_cooling_radiator"
    ]
    assert "part_subtype" in {
        conflict["dimension"] for conflict in matrix["hard_stop_conflicts"]
    }


def test_a_bare_top_mount_is_still_not_a_top_mount_bearing() -> None:
    matrix = _matrix(
        _LIVE_TOP_MOUNT_BEARING_SEED,
        "Опора амортизатора переднього VW Golf 5 1K0412331B",
    )

    assert matrix["candidate"]["part_subtype"]["values"] == ["top_mount"]
    assert "part_subtype" in {
        conflict["dimension"] for conflict in matrix["hard_stop_conflicts"]
    }


#: Subtypes whose wording is a special case of a broader rule's wording.
#:
#: ``extract_semantic_features`` takes the first matching entry of
#: ``_PART_PATTERNS`` and stops, so a broad rule placed above a narrow one
#: silences the narrow one permanently and no other test notices. That defect
#: has now shipped three times: shadow-doc defects #2 and #9, and the
#: 2026-08-06 measurement where ``top_mount`` sat 76 rules above
#: ``top_mount_bearing`` and cost 16 of 55 live hard stops. Declaring the
#: intended precedence is what makes a reordering fail loudly.
_REQUIRED_SUBTYPE_PRECEDENCE: tuple[tuple[str, str], ...] = (
    ("top_mount_bearing", "top_mount"),
    ("transmission_mount", "engine_or_transmission_mount"),
    ("top_mount_bearing", "generic_bearing"),
    ("top_mount_bearing", "shock_absorber"),
    ("wheel_bearing", "generic_bearing"),
    ("intercooler", "engine_cooling_radiator"),
    ("radiator_tank", "engine_cooling_radiator"),
    ("brake_line", "brake_hose"),
    ("window_regulator_motor", "window_regulator"),
)


#: Rules this check found already unreachable on 2026-08-06, left unfixed here.
#:
#: Each is a separate classification decision needing its own evidence, and
#: some may be deliberate — ``transmission_mount`` sitting behind
#: ``engine_or_transmission_mount`` reads as intended. They are named rather
#: than hidden so the set can only shrink: a rule that becomes shadowed by a
#: future reordering is not in this list and fails the assertion.
_KNOWN_SHADOWED_SUBTYPES: frozenset[str] = frozenset(
    {
        "",
        "alternator_rectifier",
        "alternator_roller",
        "brake_wear_sensor",
        "bulb",
        "camshaft_bearing",
        "carburetor_repair_kit",
        "distributor_vacuum_advance",
        "door_lock_cylinder",
        "lock_eccentric",
        "transmission_mount",
    }
)


def _first_rule_index_by_subtype() -> dict[str, int]:
    indices: dict[str, int] = {}
    for index, (_family, subtype, _assembly, _patterns) in enumerate(_PART_PATTERNS):
        indices.setdefault(subtype, index)
    return indices


@pytest.mark.parametrize(("specific", "generic"), _REQUIRED_SUBTYPE_PRECEDENCE)
def test_a_specific_part_rule_precedes_the_broader_rule_it_refines(
    specific: str,
    generic: str,
) -> None:
    indices = _first_rule_index_by_subtype()

    assert specific in indices, f"{specific} is no longer a declared subtype"
    assert generic in indices, f"{generic} is no longer a declared subtype"
    assert indices[specific] < indices[generic], (
        f"{specific} (rule {indices[specific]}) must be matched before "
        f"{generic} (rule {indices[generic]}); the first match wins"
    )


def test_every_part_rule_is_reachable_by_at_least_one_of_its_own_patterns() -> None:
    """No rule may be fully shadowed by the ones above it.

    The witness for a pattern is built by stripping the regex syntax this
    module actually uses, so patterns relying on anchors, optional literals or
    character classes are skipped rather than guessed at. That covered 192 of
    the 439 rules on 2026-08-06; the floor below exists so the check cannot
    quietly degrade to covering nothing.
    """

    checked = 0
    shadowed: list[str] = []
    for index, (_family, subtype, _assembly, patterns) in enumerate(_PART_PATTERNS):
        witnesses = [
            witness for pattern in patterns if (witness := _regex_witness(pattern))
        ]
        if not witnesses:
            continue
        checked += 1
        reachable = False
        for witness in witnesses:
            claimed_by = _first_matching_subtype(witness, limit=index + 1)
            if claimed_by == subtype:
                reachable = True
                break
        if not reachable:
            shadowed.append(subtype)

    assert checked >= 175, f"witness coverage collapsed to {checked} rules"
    assert set(shadowed) <= _KNOWN_SHADOWED_SUBTYPES, (
        "a part rule became unreachable behind an earlier one: "
        f"{sorted(set(shadowed) - _KNOWN_SHADOWED_SUBTYPES)}"
    )


def _first_matching_subtype(text: str, *, limit: int) -> str | None:
    for _family, subtype, _assembly, patterns in _PART_PATTERNS[:limit]:
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return subtype
    return None


def _regex_witness(pattern: str) -> str | None:
    """Build a plain string that the pattern matches, or None if unsupported."""

    if any(token in pattern for token in ("^", "$", "(?=", "(?!", "(?<", "[")):
        return None
    if re.search(r"(?<!\))(?<!\*)\?", pattern):
        # An optional literal (``a/?c``) would need both readings to be tried;
        # a witness built from one of them is not evidence about the other.
        return None
    text = pattern
    text = re.sub(r"\(\?:([^()|]*)\|[^()]*\)", r"\1", text)
    text = re.sub(r"\(\?:([^()]*)\)\?", "", text)
    text = re.sub(r"\(\?:([^()]*)\)", r"\1", text)
    if "(" in text or ")" in text or "|" in text:
        return None
    text = text.replace(r"\w*", "").replace(r"\w+", "x")
    text = text.replace(r"\s+", " ").replace(r"\s*", " ")
    text = re.sub(r"\{0,\d+\}", " ", text)
    text = text.replace(r"\d", "1").replace(r"\.", ".").replace(r"\b", "")
    if "\\" in text:
        return None
    return " ".join(text.split()) or None


def test_an_engine_mount_is_not_a_gearbox_mount() -> None:
    """Two different sellable parts that matched cleanly, with no hard stop.

    ``engine_or_transmission_mount`` names an ambiguity its own patterns do not
    have: ``подушка двигателя`` says engine and ``подушка КПП`` says gearbox.
    Collapsing both into one subtype let the semantic gate confirm a match
    between them, which is the failure the gate exists to catch — identity says
    yes and the part is still wrong.
    """

    matrix = _matrix(
        "Подушка двигателя правая VW Golf 5 1K0199262",
        "Подушка КПП Renault Megane 8200352475",
    )

    assert matrix["candidate"]["part_subtype"]["values"] == ["transmission_mount"]
    assert "part_subtype" in {
        conflict["dimension"] for conflict in matrix["hard_stop_conflicts"]
    }


@pytest.mark.parametrize(
    "title",
    (
        "Подушка КПП Renault Megane 8200352475",
        "Подушка коробки передач Ford Focus",
        "Подушка АКПП Toyota Camry",
        "Подушка МКПП Opel Astra H",
    ),
)
def test_gearbox_mount_wording_reaches_its_own_subtype(title: str) -> None:
    features = extract_semantic_features({"title": title})

    assert features["part_subtype"].values == ("transmission_mount",)


@pytest.mark.parametrize(
    "title",
    (
        "Подушка двигателя правая VW Golf 5",
        "Опора двигуна права Skoda Octavia",
    ),
)
def test_engine_mount_wording_is_unchanged(title: str) -> None:
    features = extract_semantic_features({"title": title})

    assert features["part_subtype"].values == ("engine_or_transmission_mount",)


@pytest.mark.parametrize(
    "title",
    (
        "Протитуманна фара Audi 100 91-94 ліва (FPS) 4A0941699",
        "Протитуманна фара для AUDI 100 '91-94 ліва (Depo)",
        "Фара противотуманна AUDI 100 C4 Avant DEPO 441-2026L-UE",
        "Ліва Протитуманка Audi 100 C4 1991-1994 без лінзи",
        "Противотуманка Audi (Ауді)-100 91-94 L левая",
    ),
)
def test_ukrainian_fog_lamp_wording_reaches_its_own_subtype(title: str) -> None:
    """Adjective-first Ukrainian wording is the same part as the seed's noun.

    Six offers carrying the exact OE 4A0941699 met the pricing gate with no
    part family at all, because the lexicon knew "протитуманка" and the
    Russian "фара противотуманная" but not "протитуманна фара".
    """

    features = extract_semantic_features({"title": title})

    assert features["part_family"].values == ("vehicle_lighting",)
    assert features["part_subtype"].values == ("fog_lamp",)


def test_fog_lamp_frame_still_outranks_the_lamp_itself() -> None:
    features = extract_semantic_features(
        {"title": "Рамка кріплення протитуманної фари Skoda Octavia"}
    )

    assert features["part_subtype"].values == ("fog_lamp_frame",)


def test_applicability_table_engine_power_is_not_a_part_power_rating() -> None:
    """Vehicle engine power is not the part's own rating.

    A Prom applicability table repeats one row per engine variant, and three
    such rows made a fog lamp assert three contradictory power ratings, which
    the pricing gate read as the listing contradicting itself.
    """

    features = extract_semantic_features(
        {
            "title": "Фара противотуманна AUDI 100 C4 Avant DEPO 441-2026L-UE",
            "description": (
                "AUDI 100 C4 Avant (4A5) [12/90-11/94] 2.0 E (1984ccm\\74kW\\100HP)\n"
                "AUDI 100 C4 Avant (4A5) 2.0 E (1984ccm\\85kW\\115HP)\n"
                "AUDI 100 C4 Avant (4A5) 2.0 E 16V (1984ccm\\103kW\\140HP)"
            ),
        }
    )

    assert features["power_rating"].values == ()


def test_a_part_that_really_states_its_power_still_reports_it() -> None:
    features = extract_semantic_features({"title": "Мотор пічки 0.15 кВт Renault Master"})

    assert features["power_rating"].values == ("0.15kw",)


@pytest.mark.parametrize(
    "title",
    (
        "VW T4 90-04 Візок з розсувними дверима права ЦЕНТР",
        "Каретка сдвижной двери VW Transporter T4 средняя",
        "Візок зсувних дверей Volkswagen T4 середній з роликами",
    ),
)
def test_sliding_door_carriage_wording_is_the_bracket(title: str) -> None:
    """A carriage ("візок"/"каретка") is the part the OE catalogue calls a bracket.

    Four exact-OE 701843336A listings met the pricing gate with no part family
    at all, because the lexicon only knew the "кронштейн" wording for the VW T4
    sliding-door roller carriage.
    """

    features = extract_semantic_features({"title": title})

    assert features["part_family"].values == ("door_hardware",)
    assert features["part_subtype"].values == ("sliding_door_bracket",)


def test_a_plain_door_guide_still_asserts_no_carriage_subtype() -> None:
    # "Направляюча" without the sliding-door wording stays family-less: a
    # window or seat guide must not silently join the carriage cohort.
    features = extract_semantic_features(
        {"title": "Направляюча двері VW T4 California STARLINE JL 54333 UA"}
    )

    assert features["part_subtype"].values == ()
