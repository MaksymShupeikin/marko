import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/features/pricing/pricing_api.dart';
import 'package:marko_client/features/pricing/pricing_models.dart';

void main() {
  test('loads one recommendation by its stable deep-link id', () async {
    final api = PricingApi(
      ApiClient(
        client: MockClient((request) async {
          expect(request.url.path, '/api/v1/pricing/recommendations/rec-1');
          return http.Response(jsonEncode(_recommendationJson), 200);
        }),
        baseUrl: 'http://api.test',
      ),
    );

    final recommendation = await api.getRecommendation('rec-1');

    expect(recommendation.id, 'rec-1');
    expect(recommendation.name, 'Brake pad');
  });

  test('requests all recommendations by literal absolute change', () async {
    final api = PricingApi(
      ApiClient(
        client: MockClient((request) async {
          expect(request.url.path, '/api/v1/pricing/recommendations');
          expect(
            request.url.queryParameters['sort'],
            'ABSOLUTE_RECOMMENDED_CHANGE',
          );
          expect(request.url.queryParameters['queue'], 'all');
          expect(request.url.queryParameters['action'], 'RAISE');
          expect(request.url.queryParameters['limit'], '50');
          expect(request.url.queryParameters['offset'], '0');
          return http.Response(
            jsonEncode({
              'items': <dynamic>[],
              'total': 0,
              'run_id': null,
              'limit': 250,
              'offset': 0,
              'action_counts': {'raise': 0, 'lower': 0, 'review': 0, 'hold': 0},
            }),
            200,
          );
        }),
        baseUrl: 'http://api.test',
      ),
    );

    final page = await api.listRecommendations(action: 'RAISE');

    expect(page.items, isEmpty);
    expect(page.total, 0);
    expect(page.limit, 250);
    expect(page.offset, 0);
    expect(page.actionCounts.raise, 0);
  });

  test('records an explicit recommendation decision', () async {
    final api = PricingApi(
      ApiClient(
        client: MockClient((request) async {
          expect(
            request.url.path,
            '/api/v1/pricing/recommendations/rec-1/decisions',
          );
          expect(jsonDecode(request.body)['decision'], 'overridden');
          expect(jsonDecode(request.body)['new_price'], '750.00');
          return http.Response('{}', 201);
        }),
        baseUrl: 'http://api.test',
      ),
    );

    await api.recordDecision('rec-1', {
      'decision': 'overridden',
      'new_price': '750.00',
      'allow_below_cost': false,
      'reason': 'Manual target',
    });
  });

  test('requests the manual-review queue without mixing score units', () async {
    final api = PricingApi(
      ApiClient(
        client: MockClient((request) async {
          expect(request.url.queryParameters['queue'], 'review');
          expect(request.url.queryParameters['sort'], 'REVIEW_PRIORITY');
          return http.Response(
            jsonEncode({
              'items': <dynamic>[],
              'total': 0,
              'run_id': null,
              'limit': 250,
              'offset': 0,
              'action_counts': {'raise': 0, 'lower': 0, 'review': 0, 'hold': 0},
            }),
            200,
          );
        }),
        baseUrl: 'http://api.test',
      ),
    );

    await api.listRecommendations(queue: 'review', sort: 'REVIEW_PRIORITY');
  });

  test('saves a tier override as a new classification', () async {
    final api = PricingApi(
      ApiClient(
        client: MockClient((request) async {
          expect(
            request.url.path,
            '/api/v1/pricing/observations/obs-1/tier-overrides',
          );
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          expect(body['tier'], 'aftermarket_a');
          expect(body['reason'], 'Verified manufacturer catalogue');
          return http.Response('{}', 201);
        }),
        baseUrl: 'http://api.test',
      ),
    );

    await api.overrideTier(
      'obs-1',
      tier: 'aftermarket_a',
      reason: 'Verified manufacturer catalogue',
    );
  });

  test('forces a new semantic comparability review', () async {
    final api = PricingApi(
      ApiClient(
        client: MockClient((request) async {
          expect(
            request.url.path,
            '/api/v1/pricing/observations/obs-1/comparability-reviews',
          );
          expect(jsonDecode(request.body)['force'], isTrue);
          return http.Response(jsonEncode(_comparabilityReviewJson), 200);
        }),
        baseUrl: 'http://api.test',
      ),
    );

    final review = await api.reviewComparability('obs-1', force: true);

    expect(review.verdict, 'COMPARABLE');
    expect(review.pricingEligible, isTrue);
  });

  test('records customer comparability feedback', () async {
    final api = PricingApi(
      ApiClient(
        client: MockClient((request) async {
          expect(
            request.url.path,
            '/api/v1/pricing/comparability-reviews/review-1/feedback',
          );
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          expect(body['decision'], 'CORRECT');
          expect(body['corrected_verdict'], 'NOT_COMPARABLE');
          return http.Response(jsonEncode(_comparabilityReviewJson), 201);
        }),
        baseUrl: 'http://api.test',
      ),
    );

    await api.recordComparabilityFeedback('review-1', {
      'decision': 'CORRECT',
      'corrected_verdict': 'NOT_COMPARABLE',
      'corrected_match_level': 'NOT_APPLICABLE',
      'confidence': 1,
      'reason': 'Different side',
      'evidence_corrections': <dynamic>[],
    });
  });

  test('verifies a recommendation through the replay endpoint', () async {
    final api = PricingApi(
      ApiClient(
        client: MockClient((request) async {
          expect(
            request.url.path,
            '/api/v1/pricing/recommendations/rec-1/replay',
          );
          return http.Response(
            jsonEncode({
              'recommendation_id': 'rec-1',
              'replay_contract_version': 'recommendation-replay-v1',
              'calculated_at': '2026-07-16T12:00:00Z',
              'exact_match': true,
              'mismatches': <String, dynamic>{},
              'replayed': {'action': 'RAISE'},
            }),
            200,
          );
        }),
        baseUrl: 'http://api.test',
      ),
    );

    final replay = await api.verifyReplay('rec-1');

    expect(replay.exactMatch, isTrue);
    expect(replay.contractVersion, 'recommendation-replay-v1');
    expect(replay.replayed['action'], 'RAISE');
  });

  test('preserves fail-closed comparability evidence in the UI model', () {
    final evidence = RecommendationEvidence.fromJson({
      'observation_id': 'obs-1',
      'seller_name': 'Seller',
      'title': 'Brake pad',
      'brand': 'Bosch',
      'url': 'https://fixture.invalid/obs-1',
      'price': '100.00',
      'currency': 'UAH',
      'currency_raw': null,
      'currency_inferred': false,
      'match_confidence': '1',
      'source_confidence': '1',
      'age_hours': '0',
      'tier': 'budget',
      'tier_confidence': '1',
      'is_dumping': false,
      'exclusion_reason': 'MANUAL_MISSING_RAW_CURRENCY',
      'observed_at': '2026-07-18T00:00:00Z',
      'automatic_eligible': false,
      'comparison_evidence': {
        'hard_gate_result': 'MANUAL_REVIEW',
        'reason_codes': ['MANUAL_MISSING_RAW_CURRENCY'],
      },
    });

    expect(evidence.automaticEligible, isFalse);
    expect(evidence.currencyRaw, isNull);
    expect(evidence.comparisonEvidence?['hard_gate_result'], 'MANUAL_REVIEW');
  });
}

final Map<String, dynamic> _recommendationJson = {
  'id': 'rec-1',
  'pricing_run_id': 'run-1',
  'catalog_snapshot_id': 'snapshot-1',
  'catalog_item_id': 'item-1',
  'sku': 'SKU-1',
  'oe_norm': 'OE1',
  'name': 'Brake pad',
  'category': 'brake_pads',
  'stock_status': 'fresh',
  'action': 'RAISE',
  'current_price': '100.00',
  'fair_price': '120.00',
  'recommended_price': '120.00',
  'confidence': '0.9',
  'confidence_grade': 'A',
  'competitor_count': 4,
  'priority_score': '20.00',
  'priority_score_type': 'gross_uplift_opportunity',
  'reason_codes': ['BELOW_FAIR_PRICE'],
  'currency': 'UAH',
  'price_tick': '0.50',
  'computed_at': '2026-07-30T12:00:00Z',
};

final Map<String, dynamic> _comparabilityReviewJson = {
  'review_id': 'review-1',
  'market_observation_id': 'obs-1',
  'input_hash': 'abc',
  'verdict': 'COMPARABLE',
  'match_level': 'ACCEPTABLE_ANALOGUE',
  'confidence': '0.94',
  'rationale': 'OE and part type agree.',
  'dimension_findings': [
    {
      'dimension': 'part_type',
      'outcome': 'MATCH',
      'explanation': 'Part type agrees.',
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
  'image_urls': <dynamic>[],
  'provider_response_id': 'resp-1',
  'error_code': null,
  'error_detail': null,
  'feedback_count': 0,
  'latest_feedback_id': null,
  'latest_feedback_decision': null,
  'latest_feedback_reason': null,
  'pricing_eligible': true,
};
