import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/pricing/pricing_models.dart';
import 'package:marko_client/features/pricing/recommendations_page.dart';

void main() {
  testWidgets('evidence details expose identity provenance gate and policy', (
    tester,
  ) async {
    final evidence = RecommendationEvidence.fromJson({
      'observation_id': 'obs-1',
      'seller_id': 'seller-17',
      'seller_name': 'Seller',
      'title': 'Brake pad',
      'description_available': false,
      'condition_state': 'NEW',
      'condition_reason_codes': ['EXPLICIT_NEW'],
      'cross_candidates': <dynamic>[],
      'brand': 'Bosch',
      'search_oe_norm': 'ABC123',
      'extracted_oe_norms': ['ABC123', 'DEF456'],
      'verified_matched_oe_norm': 'ABC123',
      'comparison_identity_key': 'OE:ABC123',
      'oe_verification_status': 'VERIFIED_EXACT',
      'oe_evidence_summary': [
        {'source': 'title', 'oe': 'ABC123'},
      ],
      'oe_extractor_version': 'oe-v3',
      'oe_reenriched_at': '2026-07-16T11:30:00Z',
      'oe_reenrichment_error_code': null,
      'url': 'https://example.test/item',
      'price': '2400',
      'currency': 'UAH',
      'currency_inferred': false,
      'is_available': true,
      'match_confidence': '0.95',
      'source_confidence': '0.91',
      'source_confidence_factors': {'url': '1', 'freshness': '0.9'},
      'source_confidence_method_version': 'source-confidence-v2',
      'age_hours': '2.4',
      'tier': 'oem',
      'tier_confidence': '0.93',
      'is_used': false,
      'is_kemp': false,
      'is_owned': false,
      'is_dumping': false,
      'cohort_role': 'TARGET_MARKET',
      'target_effect': 'IN_TARGET_MEDIAN',
      'observed_at': '2026-07-16T12:00:00Z',
      'automatic_eligible': true,
      'comparability_hard_gate_result': 'PASS',
      'calibration_exclusion_codes': ['CAL_OUTLIER'],
      'offer_outcome_counts': {'accepted': 3, 'rejected': 1},
      'comparability_policy_id': 'comparability-v3',
      'comparability_policy_hash': 'abc123policyhash',
    });

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: Scaffold(
          body: SingleChildScrollView(
            child: RecommendationEvidenceDetails(evidence: evidence),
          ),
        ),
      ),
    );

    expect(find.textContaining('VERIFIED_EXACT'), findsOneWidget);
    expect(find.textContaining('OE:ABC123'), findsOneWidget);
    expect(find.textContaining('source-confidence-v2'), findsOneWidget);
    expect(find.textContaining('CAL_OUTLIER'), findsOneWidget);
    expect(find.textContaining('comparability-v3'), findsOneWidget);
    expect(find.textContaining('abc123policyhash'), findsOneWidget);
    expect(find.textContaining('"accepted":3'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
