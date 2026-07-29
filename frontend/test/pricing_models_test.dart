import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/features/pricing/pricing_models.dart';

void main() {
  test('parses an actionable recommendation with Decimal strings', () {
    final item = PricingRecommendation.fromJson({
      'id': 'recommendation-id',
      'pricing_run_id': 'run-id',
      'catalog_item_id': 'item-id',
      'sku': 'SKU-1',
      'oe_norm': '06A115105B',
      'name': 'Фильтр',
      'category': 'Фильтры',
      'stock_status': 'fresh',
      'context_snapshot': {
        'stock_status': 'fresh',
        'expected_units_sold': '10',
      },
      'calculation_trace': {
        'normalized_offers': [
          {
            'observation_id': 'obs-1',
            'raw_price': '2000',
            'multiplier': '2',
            'normalized_price': '1000',
          },
        ],
      },
      'action': 'RAISE',
      'current_price': '800.00',
      'fair_price': '1100.00',
      'recommended_price': '920.00',
      'lower_bound': '1050.00',
      'upper_bound': '1150.00',
      'confidence': '0.81',
      'confidence_grade': 'A',
      'weakest_factor': 'coverage',
      'factor_scores': {'coverage': '0.74', 'match': '0.95'},
      'competitor_count': 5,
      'raw_competitor_count': 7,
      'unique_seller_count': 6,
      'clean_competitor_count': 5,
      'target_market_count': 5,
      'kemp_reference_count': 2,
      'owned_store_count': 1,
      'rejected_count': 3,
      'effective_competitor_count': '4.8',
      'dispersion': '0.04',
      'outlier_method': 'mad',
      'outlier_count': 1,
      'sensitivity': '0.01',
      'action_gates_passed': true,
      'priority_score': '972.00',
      'priority_score_type': 'gross_uplift_opportunity',
      'review_priority': '0',
      'absolute_recommended_change': '120',
      'percentage_recommended_change': '0.15',
      'reason_codes': ['MARKET_SUPPORTS_RAISE'],
      'computed_at': '2026-07-16T12:00:00Z',
    });

    expect(item.isRaise, isTrue);
    expect(item.recommendedPrice, 920);
    expect(item.confidence, 0.81);
    expect(item.actionLabel, 'Поднять цену');
    expect(item.reasonSummary, contains('рынок'));
    expect(item.contextSnapshot['expected_units_sold'], '10');
    expect(item.normalizedOffersById['obs-1']?['normalized_price'], '1000');
    expect(item.rawCompetitorCount, 7);
    expect(item.uniqueSellerCount, 6);
    expect(item.cleanCompetitorCount, 5);
    expect(item.targetMarketCount, 5);
    expect(item.kempReferenceCount, 2);
    expect(item.absoluteRecommendedChange, 120);
    expect(item.percentageRecommendedChange, 0.15);
    expect(item.effectiveCompetitorCount, 4.8);
    expect(item.actionGatesPassed, isTrue);
    expect(item.priorityLabel, contains('UAH/мес.'));
  });

  test('marks abstention as manual review', () {
    final json = {
      'id': 'recommendation-id',
      'pricing_run_id': 'run-id',
      'catalog_item_id': 'item-id',
      'sku': 'SKU-1',
      'oe_norm': 'ABC123',
      'name': 'Part',
      'category': 'Parts',
      'stock_status': 'unknown',
      'action': 'INSUFFICIENT_DATA',
      'current_price': '100',
      'fair_price': null,
      'recommended_price': null,
      'lower_bound': null,
      'upper_bound': null,
      'confidence': '0',
      'confidence_grade': 'MANUAL',
      'weakest_factor': null,
      'factor_scores': <String, dynamic>{},
      'competitor_count': 0,
      'dispersion': null,
      'priority_score': '0',
      'priority_score_type': 'none',
      'review_priority': '0',
      'reason_codes': ['TOO_FEW_COMPETITORS'],
      'computed_at': '2026-07-16T12:00:00Z',
    };

    expect(PricingRecommendation.fromJson(json).needsReview, isTrue);
  });

  test('parses raw and KEMP-normalized market evidence', () {
    final evidence = RecommendationEvidence.fromJson({
      'observation_id': 'obs-1',
      'seller_name': 'Seller',
      'title': 'OEM part',
      'description': 'Новая деталь',
      'description_available': true,
      'condition_raw': 'новая',
      'condition_state': 'NEW',
      'condition_reason_codes': ['EXPLICIT_NEW'],
      'cross_candidates': <dynamic>[],
      'brand': 'VAG',
      'url': 'https://example.test/item',
      'url_absence_reason': null,
      'price': '2400',
      'currency': 'UAH',
      'match_confidence': '0.95',
      'source_confidence': '1',
      'age_hours': '2.4',
      'tier': 'oem',
      'tier_confidence': '0.93',
      'is_dumping': false,
      'cohort_role': 'TARGET_MARKET',
      'target_effect': 'IN_TARGET_MEDIAN',
      'exclusion_reason': null,
      'normalized_price': '1000',
      'multiplier': '2.4',
      'coefficient_model': 'shrinkage',
      'coefficient_version': 'tier-shrinkage-v2:dataset',
      'coefficient_confidence': '0.88',
      'observed_at': '2026-07-16T12:00:00Z',
    });

    expect(evidence.price, 2400);
    expect(evidence.normalizedPrice, 1000);
    expect(evidence.multiplier, 2.4);
    expect(evidence.coefficientModel, 'shrinkage');
    expect(evidence.tierLabel, 'OEM');
    expect(evidence.affectsTargetMedian, isTrue);
    expect(evidence.conditionState, 'NEW');
  });

  test('does not invent maximum source confidence when it is absent', () {
    final evidence = RecommendationEvidence.fromJson({
      'observation_id': 'obs-1',
      'seller_name': 'Seller',
      'title': 'Part',
      'description_available': false,
      'condition_state': 'UNKNOWN',
      'url': 'https://example.test/item',
      'price': '100',
      'currency': 'UAH',
      'tier': 'unknown',
      'is_dumping': false,
      'observed_at': '2026-07-16T12:00:00Z',
    });

    expect(evidence.sourceConfidence, isNull);
  });

  test('parses field-level recommendation replay drift', () {
    final replay = RecommendationReplay.fromJson({
      'recommendation_id': 'rec-1',
      'replay_contract_version': 'recommendation-replay-v1',
      'calculated_at': '2026-07-16T12:00:00Z',
      'exact_match': false,
      'mismatches': {
        'recommended_price': {'stored': '920.00', 'replayed': '921.00'},
      },
      'replayed': {'action': 'RAISE'},
    });

    expect(replay.exactMatch, isFalse);
    expect(replay.mismatches.keys, contains('recommended_price'));
  });
}
