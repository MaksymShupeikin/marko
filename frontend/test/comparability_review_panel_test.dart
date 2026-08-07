import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/pricing/comparability_review_panel.dart';
import 'package:marko_client/features/pricing/pricing_models.dart';

void main() {
  testWidgets('shows verdict rationale evidence and advisory-only boundary', (
    tester,
  ) async {
    final evidence = RecommendationEvidence.fromJson({
      'observation_id': 'obs-1',
      'seller_id': 'seller-1',
      'seller_name': 'Seller',
      'title': 'Brake disc',
      'url': 'https://example.test/item',
      'price': '1000',
      'currency': 'UAH',
      'tier': 'budget',
      'is_dumping': false,
      'observed_at': '2026-07-31T12:00:00Z',
      'llm_review_required': true,
      'llm_pricing_eligible': true,
      'llm_review': {
        'review_id': 'review-1',
        'market_observation_id': 'obs-1',
        'input_hash': 'abc',
        'contract_version': 'comparability-v2',
        'verdict': 'COMPARABLE',
        'match_level': 'ACCEPTABLE_ANALOGUE',
        'confidence': '0.94',
        'identity_verdict': 'MATCH',
        'identity_match_level': 'ACCEPTABLE_ANALOGUE',
        'identity_match_score': '0.94',
        'decision_confidence': '0.91',
        'image_consistency': 'SUPPORTS',
        'reason_codes': ['OE_AND_PART_TYPE_MATCH'],
        'pricing_admission': 'ADMITTED',
        'pricing_reason_codes': ['PRICING_EVIDENCE_COMPLETE'],
        'rationale': 'OE and part type agree.',
        'dimension_findings': [
          {
            'dimension': 'oe_reference',
            'outcome': 'MATCH',
            'our_value': '1K0615301',
            'candidate_value': '1K0615301',
            'explanation': 'Normalized OE identifiers match.',
            'evidence': [
              {
                'source': 'CANDIDATE',
                'field': 'description',
                'value': 'OE 1K0615301',
                'excerpt': 'Brake disc OE 1K0615301',
              },
            ],
          },
          {
            'dimension': 'part_type',
            'outcome': 'MATCH',
            'explanation': 'Both cards describe a brake disc.',
          },
        ],
        'hard_stop_conflicts': <dynamic>[],
        'decision_source': 'LLM',
        'status': 'COMPLETED',
        'provider': 'openai_responses',
        'model_id': 'gpt-test',
        'prompt_version': 'comparability-v1',
        'reasoning_effort': 'xhigh',
        'model_settings_hash':
            'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
        'reviewed_at': '2026-07-31T12:00:00Z',
        'cache_hit_review_id': null,
        'image_urls': <dynamic>[],
        'provider_response_id': 'resp-1',
        'usage': {'input_tokens': 120, 'output_tokens': 40},
        'latency_ms': 450,
        'estimated_cost': {'total_usd': '0.000072'},
        'rate_card_version': 'rate-v1',
        'verified_cross_edge': {
          'seed_code': '1K0615301',
          'candidate_code': '1K0615301A',
          'source_count': 2,
          'independent_seller_count': 2,
        },
        'our_product': {
          'name': 'Наш тормозной диск',
          'sku': 'SKU-1',
          'oe_norm': '1K0615301',
        },
        'candidate': {'title': 'Brake disc'},
        'error_code': null,
        'error_detail': null,
        'feedback_count': 0,
        'latest_feedback_id': null,
        'latest_feedback_decision': null,
        'latest_feedback_reason': null,
        'pricing_eligible': true,
      },
    });

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: Scaffold(body: ComparabilityReviewPanel(evidence: evidence)),
      ),
    );

    expect(find.textContaining('Identity совпадает'), findsOneWidget);
    expect(find.textContaining('94%'), findsOneWidget);
    expect(find.textContaining('некалиброванный'), findsOneWidget);
    expect(find.textContaining('Pricing: ADMITTED'), findsOneWidget);
    expect(find.textContaining('Цена кандидата: 1000.00 UAH'), findsOneWidget);
    expect(find.textContaining('Наш тормозной диск'), findsOneWidget);
    expect(find.text('OE and part type agree.'), findsOneWidget);
    expect(
      find.textContaining('Normalized OE identifiers match.'),
      findsOneWidget,
    );
    expect(find.textContaining('Наше: 1K0615301'), findsOneWidget);
    expect(find.textContaining('Карточка конкурента'), findsOneWidget);
    expect(find.textContaining('Brake disc OE 1K0615301'), findsOneWidget);
    expect(find.textContaining('estimated cost=0.000072 USD'), findsOneWidget);
    expect(find.textContaining('Cross CONFIRMED'), findsOneWidget);
    expect(find.textContaining('не публикуется автоматически'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('missing required review is explicitly excluded', (tester) async {
    final evidence = RecommendationEvidence.fromJson({
      'observation_id': 'obs-2',
      'seller_name': 'Seller',
      'title': 'Unknown part',
      'url': '',
      'price': '900',
      'currency': 'UAH',
      'tier': 'unknown',
      'is_dumping': false,
      'observed_at': '2026-07-31T12:00:00Z',
      'llm_review_required': true,
      'llm_pricing_eligible': false,
    });

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: Scaffold(body: ComparabilityReviewPanel(evidence: evidence)),
      ),
    );

    expect(
      find.textContaining('Кандидат исключён из ценового расчёта'),
      findsOneWidget,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('hides candidate price until pricing admission', (tester) async {
    final evidence = RecommendationEvidence.fromJson({
      'observation_id': 'obs-3',
      'seller_name': 'Seller',
      'title': 'Wrong-side brake disc',
      'url': 'https://example.test/item',
      'price': '777',
      'currency': 'UAH',
      'tier': 'budget',
      'is_dumping': false,
      'observed_at': '2026-07-31T12:00:00Z',
      'llm_review_required': true,
      'llm_pricing_eligible': false,
      'llm_review': {
        'review_id': 'review-3',
        'market_observation_id': 'obs-3',
        'input_hash': 'hash',
        'contract_version': 'comparability-v2',
        'verdict': 'NOT_COMPARABLE',
        'match_level': 'NOT_APPLICABLE',
        'confidence': '1',
        'identity_verdict': 'NOT_MATCH',
        'identity_match_level': 'NOT_APPLICABLE',
        'identity_match_score': '0',
        'decision_confidence': '1',
        'image_consistency': 'NON_DIAGNOSTIC',
        'reason_codes': ['SIDE_CONFLICT'],
        'pricing_admission': 'EXCLUDED',
        'pricing_reason_codes': ['HARD_STOP_SIDE'],
        'rationale': 'Side conflicts.',
        'dimension_findings': <dynamic>[],
        'hard_stop_conflicts': <dynamic>[],
        'decision_source': 'HARD_RULE',
        'status': 'HARD_STOP',
        'provider': 'openai_responses',
        'model_id': 'gpt-5.6-luna',
        'prompt_version': 'comparability-v2',
        'reviewed_at': '2026-07-31T12:00:00Z',
        'image_urls': <dynamic>[],
        'pricing_eligible': false,
      },
    });

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: Scaffold(body: ComparabilityReviewPanel(evidence: evidence)),
      ),
    );

    expect(find.textContaining('Цена скрыта до ADMITTED'), findsOneWidget);
    expect(find.textContaining('777.00 UAH'), findsNothing);
    expect(find.textContaining('HARD_STOP_SIDE'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
