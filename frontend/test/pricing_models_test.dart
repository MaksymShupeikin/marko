import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/presentation_formatters.dart';
import 'package:marko_client/features/pricing/pricing_models.dart';

void main() {
  test('pricing preview separates scope rows from matchable rows', () {
    final preview = PricingRunPreview.fromJson({
      'scope_mode': 'FULL_CATALOG',
      'scope_hash': 'scope-hash',
      'catalog_snapshot_hash': 'catalog-hash',
      'preview_token': 'preview-token',
      'requires_full_catalog_confirmation': true,
      'estimate': {
        'requested_items': 4901,
        'eligible_items': 4901,
        'excluded_items': 0,
        'network_eligible_items': 4861,
        'identity_blocked_items': 40,
        'worst_case_duration_seconds': 7200,
      },
    });

    expect(preview.eligibleItems, 4901);
    expect(preview.networkEligibleItems, 4861);
    expect(preview.identityBlockedItems, 40);
    expect(preview.worstCaseMinutes, 120);
  });

  test('legacy pricing preview treats all eligible rows as matchable', () {
    final preview = PricingRunPreview.fromJson({
      'estimate': {'eligible_items': 12},
    });

    expect(preview.networkEligibleItems, 12);
    expect(preview.identityBlockedItems, 0);
  });

  test(
    'parses comparability-v2 identity, admission and cost independently',
    () {
      final review = ComparabilityReview.fromJson({
        'review_id': 'review-v2',
        'market_observation_id': 'obs-v2',
        'input_hash': 'hash-v2',
        'contract_version': 'comparability-v2',
        'verdict': 'INSUFFICIENT_DATA',
        'match_level': 'SUSPICIOUS',
        'confidence': '0.88',
        'identity_verdict': 'MATCH',
        'identity_match_level': 'ACCEPTABLE_ANALOGUE',
        'identity_match_score': '0.91',
        'decision_confidence': '0.88',
        'image_consistency': 'NON_DIAGNOSTIC',
        'reason_codes': ['IDENTITY_MATCH'],
        'pricing_admission': 'MANUAL_REVIEW',
        'pricing_reason_codes': ['PRICING_EVIDENCE_MISSING_UNIT_BASIS'],
        'rationale': 'Identity matches, unit basis is missing.',
        'dimension_findings': <dynamic>[],
        'hard_stop_conflicts': <dynamic>[],
        'decision_source': 'LLM',
        'status': 'COMPLETED',
        'provider': 'openai_responses',
        'model_id': 'gpt-5.6-luna',
        'prompt_version': 'comparability-v2',
        'reasoning_effort': 'xhigh',
        'reviewed_at': '2026-08-04T12:00:00Z',
        'image_urls': <dynamic>[],
        'usage': {'input_tokens': 100, 'output_tokens': 20},
        'latency_ms': 321,
        'estimated_cost': {'total_usd': '0.000044'},
        'verified_cross_edge': <String, dynamic>{},
        'our_product': {'sku': 'SKU-1'},
        'candidate': {'seller_id': 'seller-1'},
        'pricing_eligible': false,
      });

      expect(review.identityVerdict, 'MATCH');
      expect(review.identityMatchScore, 0.91);
      expect(review.pricingAdmission, 'MANUAL_REVIEW');
      expect(review.pricingEligible, isFalse);
      expect(review.reasoningEffort, 'xhigh');
      expect(review.estimatedCostUsd, '0.000044');
    },
  );

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
    expect(item.recommendedPrice, DecimalValue.parse('920'));
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
    expect(item.absoluteRecommendedChange, DecimalValue.parse('120'));
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

  test('keeps MPN-only identity separate from OE', () {
    final item = PricingRecommendation.fromJson({
      'id': 'recommendation-mpn',
      'pricing_run_id': 'run-id',
      'catalog_item_id': 'item-id',
      'sku': '77641360',
      'oe_norm': '',
      'mpn_norm': '115',
      'search_identity': '115070',
      'identity_status': 'MPN_ONLY',
      'name': 'Part',
      'category': 'Parts',
      'stock_status': 'unknown',
      'action': 'MANUAL_REVIEW',
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
      'raw_competitor_count': 0,
      'unique_seller_count': 0,
      'clean_competitor_count': 0,
      'target_market_count': 0,
      'kemp_reference_count': 0,
      'owned_store_count': 0,
      'rejected_count': 0,
      'effective_competitor_count': '0',
      'dispersion': null,
      'outlier_method': 'none',
      'outlier_count': 0,
      'sensitivity': null,
      'action_gates_passed': false,
      'automatic_eligible': false,
      'verified_seller_count': 0,
      'priority_score': '0',
      'priority_score_type': 'none',
      'review_priority': '0',
      'absolute_recommended_change': null,
      'percentage_recommended_change': null,
      'reason_codes': <dynamic>['IDENTITY_EVIDENCE_INSUFFICIENT'],
      'computed_at': '2026-08-06T12:00:00Z',
    });

    expect(item.oe, isEmpty);
    expect(item.mpn, '115');
    expect(item.searchIdentity, '115070');
    expect(item.identityStatus, 'MPN_ONLY');
  });

  test('parses catalog evidence without promoting candidate numbers to OE', () {
    final evidence = CatalogDataEvidence.fromJson({
      'status': 'CANDIDATE_REVIEW',
      'review_only': true,
      'internal_code': '77643',
      'oe_sources': ['OWN_EXPORT_CODE', 'KEMP_REFERENCE_MAP_V2'],
      'evidence_url': 'https://example.test/confirm',
      'confirmed_cross_numbers': ['93818439'],
      'candidate_numbers': ['93818440'],
      'anomalies': ['SHARED_ARTICLE_FANOUT'],
      'no_oe_reason': 'нужна независимая проверка',
    });

    expect(evidence.status, 'CANDIDATE_REVIEW');
    expect(evidence.reviewOnly, isTrue);
    expect(evidence.internalCode, '77643');
    expect(evidence.oeSources, ['OWN_EXPORT_CODE', 'KEMP_REFERENCE_MAP_V2']);
    expect(evidence.confirmedCrossNumbers, ['93818439']);
    expect(evidence.candidateNumbers, ['93818440']);
    expect(evidence.noOeReason, 'нужна независимая проверка');
  });

  test('parses the gated budget-floor target as a non-applying advisory', () {
    final item = PricingRecommendation.fromJson({
      'id': 'recommendation-id',
      'pricing_run_id': 'run-id',
      'catalog_item_id': 'item-id',
      'sku': 'SKU-1',
      'oe_norm': 'ABC123',
      'name': 'Part',
      'category': 'Parts',
      'stock_status': 'dead_stock',
      'calculation_trace': {
        'customer_pricing_policy': {
          'strategy': 'budget_floor',
          'minimum_discount': '0.05',
          'maximum_discount': '0.05',
          'brand_tier_handling': 'ignored_for_price',
          'stock_status_handling': 'ignored_for_price',
          'purchase_cost_handling': 'ignored_for_price',
        },
        'advisory_decision': {
          'status': 'COMPARABILITY_REVIEW_REQUIRED',
          'action': 'RAISE',
          'recommended_price': '950',
          'minimum_comparable_price': '1000',
          'target_band_low': '950',
          'target_band_high': '950',
          'automatic_price_application': false,
        },
      },
      'action': 'MANUAL_REVIEW',
      'current_price': '800',
      'fair_price': '1000',
      'recommended_price': null,
      'lower_bound': '950',
      'upper_bound': '950',
      'confidence': '0.8',
      'confidence_grade': 'MANUAL',
      'weakest_factor': 'coverage',
      'factor_scores': <String, dynamic>{},
      'competitor_count': 5,
      'dispersion': '0.1',
      'priority_score': '0',
      'priority_score_type': 'none',
      'review_priority': '0',
      'reason_codes': [
        'CUSTOMER_BUDGET_FLOOR_POLICY',
        'COMPARABILITY_AUTOMATIC_ACTIVATION_BLOCKED',
      ],
      'computed_at': '2026-07-30T12:00:00Z',
    });

    expect(item.needsReview, isTrue);
    expect(item.hasAdvisoryPrice, isTrue);
    expect(item.advisoryAction, 'RAISE');
    expect(item.advisoryRecommendedPrice, DecimalValue.parse('950'));
    expect(item.advisoryMarketMinimum, DecimalValue.parse('1000'));
    expect(item.advisoryTargetBandLow, DecimalValue.parse('950'));
    expect(item.advisoryTargetBandHigh, DecimalValue.parse('950'));
    expect(
      item.customerPricingPolicy?['brand_tier_handling'],
      'ignored_for_price',
    );
  });

  test('parses raw and KEMP-normalized market evidence', () {
    final evidence = RecommendationEvidence.fromJson({
      'observation_id': 'obs-1',
      'seller_id': 'seller-17',
      'seller_name': 'Seller',
      'title': 'OEM part',
      'description': 'Новая деталь',
      'description_available': true,
      'condition_raw': 'новая',
      'condition_state': 'NEW',
      'condition_reason_codes': ['EXPLICIT_NEW'],
      'cross_candidates': <dynamic>[],
      'brand': 'VAG',
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
      'url_absence_reason': null,
      'price': '2400',
      'currency': 'UAH',
      'is_available': true,
      'match_confidence': '0.95',
      'source_confidence': '1',
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
      'exclusion_reason': null,
      'normalized_price': '1000',
      'multiplier': '2.4',
      'coefficient_model': 'shrinkage',
      'coefficient_version': 'tier-shrinkage-v2:dataset',
      'coefficient_confidence': '0.88',
      'observed_at': '2026-07-16T12:00:00Z',
      'comparability_hard_gate_result': 'PASS',
      'calibration_exclusion_codes': ['CAL_OUTLIER'],
      'offer_outcome_counts': {'accepted': 3, 'rejected': 1},
      'comparability_policy_id': 'comparability-v3',
      'comparability_policy_hash': 'abc123policyhash',
    });

    expect(evidence.price, DecimalValue.parse('2400'));
    expect(evidence.normalizedPrice, DecimalValue.parse('1000'));
    expect(evidence.multiplier, 2.4);
    expect(evidence.coefficientModel, 'shrinkage');
    expect(evidence.tierLabel, 'OEM');
    expect(evidence.affectsTargetMedian, isTrue);
    expect(evidence.conditionState, 'NEW');
    expect(evidence.sellerId, 'seller-17');
    expect(evidence.searchOeNorm, 'ABC123');
    expect(evidence.extractedOeNorms, ['ABC123', 'DEF456']);
    expect(evidence.verifiedMatchedOeNorm, 'ABC123');
    expect(evidence.comparisonIdentityKey, 'OE:ABC123');
    expect(evidence.oeVerificationStatus, 'VERIFIED_EXACT');
    expect(evidence.oeEvidenceSummary.single['source'], 'title');
    expect(evidence.oeExtractorVersion, 'oe-v3');
    expect(evidence.oeReenrichedAt, isNotNull);
    expect(evidence.oeReenrichmentErrorCode, isNull);
    expect(evidence.isAvailable, isTrue);
    expect(evidence.sourceConfidenceFactors['freshness'], '0.9');
    expect(evidence.sourceConfidenceMethodVersion, 'source-confidence-v2');
    expect(evidence.isUsed, isFalse);
    expect(evidence.isKemp, isFalse);
    expect(evidence.isOwned, isFalse);
    expect(evidence.comparabilityHardGateResult, 'PASS');
    expect(evidence.calibrationExclusionCodes, ['CAL_OUTLIER']);
    expect(evidence.offerOutcomeCounts, {'accepted': 3, 'rejected': 1});
    expect(evidence.comparabilityPolicyId, 'comparability-v3');
    expect(evidence.comparabilityPolicyHash, 'abc123policyhash');
  });

  test('parses auditable LLM comparability review and pricing gate', () {
    final evidence = RecommendationEvidence.fromJson({
      'observation_id': 'obs-llm',
      'seller_name': 'Competitor',
      'title': 'Brake disc',
      'url': 'https://example.test/item',
      'price': '1000',
      'currency': 'UAH',
      'tier': 'budget',
      'is_dumping': false,
      'observed_at': '2026-07-31T12:00:00Z',
      'candidate_snapshot': {
        'images': ['https://cdn.example.test/part.jpg'],
      },
      'llm_review_required': true,
      'llm_pricing_eligible': true,
      'llm_review': {
        'review_id': 'review-1',
        'market_observation_id': 'obs-llm',
        'input_hash': 'abc',
        'verdict': 'COMPARABLE',
        'match_level': 'ACCEPTABLE_ANALOGUE',
        'confidence': '0.94',
        'rationale': 'OE and part type agree.',
        'dimension_findings': [
          {
            'dimension': 'part_type',
            'outcome': 'MATCH',
            'explanation': 'Both are brake discs.',
          },
        ],
        'hard_stop_conflicts': <dynamic>[],
        'decision_source': 'LLM',
        'status': 'COMPLETED',
        'provider': 'openai_responses',
        'model_id': 'gpt-test',
        'prompt_version': 'comparability-v1',
        'reviewed_at': '2026-07-31T12:00:00Z',
        'cache_hit_review_id': null,
        'image_urls': ['https://cdn.example.test/part.jpg'],
        'provider_response_id': 'resp-1',
        'error_code': null,
        'error_detail': null,
        'feedback_count': 1,
        'latest_feedback_id': 'feedback-1',
        'latest_feedback_decision': 'CONFIRM',
        'latest_feedback_reason': 'Correct match',
        'pricing_eligible': true,
      },
    });

    expect(evidence.llmReviewRequired, isTrue);
    expect(evidence.llmPricingEligible, isTrue);
    expect(evidence.candidateSnapshot['images'], isNotEmpty);
    expect(evidence.llmReview?.verdict, 'COMPARABLE');
    expect(evidence.llmReview?.matchLevel, 'ACCEPTABLE_ANALOGUE');
    expect(evidence.llmReview?.confidence, 0.94);
    expect(evidence.llmReview?.dimensionFindings.single['outcome'], 'MATCH');
    expect(evidence.llmReview?.feedbackCount, 1);
    expect(evidence.llmReview?.pricingEligible, isTrue);
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
