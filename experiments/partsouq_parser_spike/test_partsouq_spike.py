from pathlib import Path
import unittest

from partsouq_spike import (
    FormalPartQuery,
    IdentifierKind,
    IdentifierSource,
    KnownIdentifier,
    QueryKind,
    ResultRole,
    build_query_plan,
    parse_saved_search_html,
    substitution_numbers,
)


ROOT = Path(__file__).resolve().parent


class QueryPlanTests(unittest.TestCase):
    def test_part_number_is_an_eligible_lookup(self) -> None:
        plan = build_query_plan(
            FormalPartQuery(
                standardized_name="engine oil filter assembly",
                part_type="oil_filter",
                known_identifiers=(
                    KnownIdentifier(
                        kind=IdentifierKind.OE,
                        value="90915-20004",
                        source=IdentifierSource.CUSTOMER_CATALOG,
                    ),
                ),
            )
        )

        self.assertEqual(plan.kind, QueryKind.PART_NUMBER)
        self.assertEqual(plan.query_value, "90915-20004")
        self.assertEqual(
            plan.url,
            "https://partsouq.com/en/search/all?q=90915-20004",
        )

    def test_vin_is_an_eligible_lookup(self) -> None:
        plan = build_query_plan(
            FormalPartQuery(
                standardized_name="front left brake caliper",
                part_type="brake_caliper",
                vin_or_frame="JTEBU14R158044640",
            )
        )

        self.assertEqual(plan.kind, QueryKind.VIN_OR_FRAME)
        self.assertEqual(plan.query_value, "JTEBU14R158044640")

    def test_even_a_detailed_name_is_not_promoted_to_a_lookup(self) -> None:
        plan = build_query_plan(
            FormalPartQuery(
                standardized_name="rear left brake caliper without carrier",
                part_type="brake_caliper",
                vehicle_makes=("Audi", "Volkswagen"),
                vehicle_models=("A4", "A6", "Passat"),
                production_years="1997+",
                position="rear",
                side="left",
            )
        )

        self.assertEqual(plan.kind, QueryKind.UNSUPPORTED_NAME_ONLY)
        self.assertIsNone(plan.url)
        self.assertEqual(
            plan.reason_code,
            "PARTSOUQ_REQUIRES_PART_NUMBER_OR_VIN_FRAME",
        )

    def test_model_inferred_number_is_not_treated_as_lookup_evidence(self) -> None:
        plan = build_query_plan(
            FormalPartQuery(
                standardized_name="engine oil filter assembly",
                part_type="oil_filter",
                known_identifiers=(
                    KnownIdentifier(
                        kind=IdentifierKind.OE,
                        value="9091520004",
                        source=IdentifierSource.MODEL_INFERRED,
                    ),
                ),
            )
        )

        self.assertEqual(plan.kind, QueryKind.UNSUPPORTED_NAME_ONLY)
        self.assertIsNone(plan.url)


class OfflineParserTests(unittest.TestCase):
    def test_saved_search_extracts_identity_and_substitutions(self) -> None:
        html = (ROOT / "fixtures/search_9091520004.synthetic.html").read_text(
            encoding="utf-8"
        )

        parts = parse_saved_search_html(html)

        self.assertEqual(len(parts), 3)
        self.assertEqual(parts[0].name, "FILTER ASSY, OIL")
        self.assertEqual(parts[0].part_number, "9091520004")
        self.assertEqual(parts[0].role, ResultRole.QUERY_RESULT)
        self.assertIn("4Runner", parts[0].compatibility)
        self.assertEqual(
            substitution_numbers(parts),
            ("90915YZZD4", "9091520002"),
        )

    def test_duplicate_offers_do_not_become_independent_identity_evidence(self) -> None:
        html = """
        <h1>FILTER ASSY, OIL</h1><h2>Part number: 9091520004</h2>
        <h1>FILTER ASSY, OIL</h1><h2>Part number: 9091520004</h2>
        """

        self.assertEqual(len(parse_saved_search_html(html)), 1)


if __name__ == "__main__":
    unittest.main()
