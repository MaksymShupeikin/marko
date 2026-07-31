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
        'verdict': 'COMPARABLE',
        'match_level': 'ACCEPTABLE_ANALOGUE',
        'confidence': '0.94',
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
      },
    });

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: Scaffold(body: ComparabilityReviewPanel(evidence: evidence)),
      ),
    );

    expect(find.textContaining('Сопоставим'), findsOneWidget);
    expect(find.textContaining('94%'), findsOneWidget);
    expect(find.text('OE and part type agree.'), findsOneWidget);
    expect(
      find.textContaining('Normalized OE identifiers match.'),
      findsOneWidget,
    );
    expect(find.textContaining('Наше: 1K0615301'), findsOneWidget);
    expect(find.textContaining('Карточка конкурента'), findsOneWidget);
    expect(find.textContaining('Brake disc OE 1K0615301'), findsOneWidget);
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
}
