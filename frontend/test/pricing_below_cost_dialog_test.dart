import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/pricing/pricing_models.dart';
import 'package:marko_client/features/pricing/recommendation_decision_dialog.dart';

void main() {
  testWidgets('records a below-cost declaration without sending raw cost', (
    tester,
  ) async {
    Map<String, dynamic>? decision;
    final recommendation = PricingRecommendation.fromJson({
      'id': 'rec-1',
      'pricing_run_id': 'run-1',
      'catalog_snapshot_id': 'snapshot-1',
      'catalog_item_id': 'item-1',
      'sku': 'SKU-1',
      'oe_norm': 'OE-1',
      'name': 'Dead-stock part',
      'category': 'Parts',
      'stock_status': 'dead_stock',
      'context_snapshot': {
        'stock_status': 'dead_stock',
        'cost_privacy_mode': 'UNDECIDED',
        'cost_configured': false,
      },
      'calculation_trace': <String, dynamic>{},
      'action': 'LOWER',
      'current_price': '1500',
      'fair_price': '850',
      'recommended_price': '850',
      'lower_bound': '800',
      'upper_bound': '900',
      'confidence': '0.8',
      'confidence_grade': 'A',
      'weakest_factor': 'coverage',
      'factor_scores': {'coverage': '0.8'},
      'competitor_count': 5,
      'effective_competitor_count': '5',
      'dispersion': '0.05',
      'priority_score': '12000',
      'priority_score_type': 'clearance_priority',
      'review_priority': '0',
      'reason_codes': ['CLEARANCE_MARKDOWN'],
      'computed_at': '2026-07-16T12:00:00Z',
    });

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: Scaffold(
          body: Builder(
            builder: (context) => FilledButton(
              onPressed: () async {
                decision = await showRecommendationDecisionDialog(
                  context,
                  recommendation: recommendation,
                  decision: 'accepted',
                );
              },
              child: const Text('Open'),
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.text('Open'));
    await tester.pumpAndSettle();
    expect(find.textContaining('локальной себестоимости'), findsWidgets);
    expect(find.textContaining('1200'), findsNothing);

    await tester.tap(
      find.text('По моей локальной себестоимости эта цена убыточна'),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('Записать'));
    await tester.pumpAndSettle();

    expect(decision?['allow_below_cost'], isTrue);
    expect(decision?['warning_confirmed'], isTrue);
    expect(decision?.containsKey('cost'), isFalse);
    expect(decision?.containsKey('below_cost_floor'), isFalse);
  });
}
