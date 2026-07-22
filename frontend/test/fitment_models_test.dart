import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/features/fitment/fitment_models.dart';

void main() {
  test('keeps compatibility separate from price comparability', () {
    final candidate = FitmentCandidate.fromJson({
      'id': 'assessment-1',
      'market_observation_id': 'observation-1',
      'seller_id': '4145355',
      'seller_name': 'AutoPartsX',
      'title': 'Амортизатор задний правый',
      'brand': 'SATO',
      'url': 'https://prom.ua/ua/p1-item.html',
      'price': '2139.00',
      'reference_price': '2400.00',
      'currency': 'UAH',
      'candidate_identity': {'axle': 'rear', 'side': 'right'},
      'candidate_commercial_context': {
        'tier': 'unknown',
        'seller_relation': 'independent',
      },
      'compatibility_status': 'likely_compatible',
      'compatibility_probability': '0.82',
      'coverage': '0.76',
      'hard_rejections': <dynamic>[],
      'reason_codes': ['MANUAL_REVIEW_REQUIRED'],
      'missing_critical_fields': <dynamic>[],
      'authoritative_confirmation': false,
      'requires_manual_review': true,
      'evidence_ids': ['evidence-1'],
      'evidence_claim_ids': ['claim-1'],
      'evidence': [
        {
          'id': 'claim-1',
          'feature': 'cross_confirmed',
          'evidence_value': '1',
          'source_type': 'official_manufacturer_catalog',
          'source_tier': 'A',
          'source_reliability': '0.95',
          'extraction_confidence': '0.90',
          'directness': '0.80',
          'independence_factor': '1',
          'freshness_factor': '1',
          'correlation_group': 'official-sato',
          'polarity': 'supports',
          'statement_status': 'FACT',
          'source_url': 'https://catalog.example/cross',
          'raw_fragment': '21956RR replaces 48530-89025',
          'retrieved_at': '2026-07-21T10:00:00Z',
        },
      ],
      'price_comparability_status': 'manual_review',
      'price_eligible': false,
      'competitor_weight': '0',
      'normalized_unit_price': '1069.50',
      'price_unit_status': 'normalized_pair',
      'price_unit_certainty': '0.95',
      'price_reason_codes': ['TIER_NOT_COMPARABLE'],
      'automatic_price_change_allowed': false,
    });

    expect(candidate.statusLabel, 'Вероятный аналог');
    expect(candidate.positionLabel, 'rear / right');
    expect(candidate.priceEligible, isFalse);
    expect(candidate.automaticPriceChangeAllowed, isFalse);
    expect(candidate.priceReasonCodes, contains('TIER_NOT_COMPARABLE'));
    expect(candidate.independentSourceCount, 1);
    expect(candidate.referencePrice, 2400);
    expect(candidate.normalizedUnitPrice, 1069.5);
    expect(candidate.priceUnitStatus, 'normalized_pair');
    expect(candidate.evidence.single.effectiveWeight, closeTo(0.684, 0.0001));
    expect(candidate.evidence.single.contradicts, isFalse);
  });

  test('parses a human-only market recommendation', () {
    final recommendation = FitmentMarketRecommendation.fromJson({
      'id': 'recommendation-1',
      'analysis_id': 'analysis-1',
      'action': 'consider_raise',
      'strategy': 'balanced',
      'current_price': '850.00',
      'recommended_price': '950.00',
      'recommended_range_min': '900.00',
      'recommended_range_max': '1100.00',
      'absolute_change': '100.00',
      'relative_change': '0.1176',
      'market_anchor': '970.00',
      'approved_price_floor': null,
      'currency': 'UAH',
      'confidence': '0.78',
      'confidence_factors': {'fitment': '0.94'},
      'market_summary': {
        'independent_seller_groups': 3,
        'effective_sample_size': '2.84',
      },
      'price_statistics': {'weighted_median': '980.00'},
      'reason_codes': ['CURRENT_PRICE_BELOW_GUARDRAILED_MARKET_TARGET'],
      'warnings': ['MARGIN_SAFETY_UNKNOWN'],
      'automatic_price_change_allowed': false,
      'created_at': '2026-07-21T10:00:00Z',
    });

    expect(recommendation.actionLabel, 'Рассмотреть повышение');
    expect(recommendation.independentSellerGroups, 3);
    expect(recommendation.effectiveSampleSize, closeTo(2.84, 0.001));
    expect(recommendation.automaticPriceChangeAllowed, isFalse);
  });

  test('parses an empty latest-analysis page without inventing candidates', () {
    final page = FitmentCandidatePage.fromJson({
      'items': <dynamic>[],
      'total': 0,
      'analysis_id': null,
    });

    expect(page.items, isEmpty);
    expect(page.total, 0);
    expect(page.analysisId, isNull);
  });
}
