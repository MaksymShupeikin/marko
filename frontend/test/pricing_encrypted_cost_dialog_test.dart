import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/pricing/catalog_context_dialog.dart';
import 'package:marko_client/features/pricing/pricing_models.dart';
import 'package:marko_client/features/pricing/recommendation_decision_dialog.dart';

void main() {
  testWidgets('submits a new cost only through encrypted-server mode', (
    tester,
  ) async {
    Map<String, dynamic>? result;
    await tester.pumpWidget(
      _dialogHost(
        onPressed: (context) async {
          result = await showCatalogContextDialog(
            context,
            initialStatus: 'fresh',
            initialContext: const {
              'stock_status': 'fresh',
              'cost_privacy_mode': 'SERVER_SIDE_ENCRYPTED',
              'cost_configured': false,
            },
          );
        },
      ),
    );

    await tester.tap(find.text('Open'));
    await tester.pumpAndSettle();
    expect(find.textContaining('AES-256-GCM'), findsOneWidget);
    expect(find.textContaining('987.65'), findsNothing);

    await tester.enterText(
      find.widgetWithText(TextField, 'Себестоимость, UAH'),
      '987,65',
    );
    await tester.tap(find.text('Сохранить'));
    await tester.pumpAndSettle();

    expect(result?['cost'], '987.65');
    expect(result?.containsKey('clear_cost'), isFalse);
    expect(result?.containsKey('cost_ciphertext'), isFalse);
    expect(result?.containsKey('cost_encryption_key'), isFalse);
  });

  testWidgets('clears configured cost without returning its old value', (
    tester,
  ) async {
    Map<String, dynamic>? result;
    await tester.pumpWidget(
      _dialogHost(
        onPressed: (context) async {
          result = await showCatalogContextDialog(
            context,
            initialStatus: 'stale',
            initialContext: const {
              'stock_status': 'stale',
              'cost_privacy_mode': 'SERVER_SIDE_ENCRYPTED',
              'cost_configured': true,
            },
          );
        },
      ),
    );

    await tester.tap(find.text('Open'));
    await tester.pumpAndSettle();
    expect(
      find.textContaining('Текущее значение намеренно не возвращается'),
      findsOneWidget,
    );

    await tester.tap(find.text('Удалить сохранённую себестоимость'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Сохранить'));
    await tester.pumpAndSettle();

    expect(result?['clear_cost'], isTrue);
    expect(result?.containsKey('cost'), isFalse);
  });

  testWidgets(
    'requires confirmation when encrypted cost exceeds recommendation',
    (tester) async {
      Map<String, dynamic>? decision;
      final recommendation = _recommendation(
        context: const {
          'stock_status': 'dead_stock',
          'cost_privacy_mode': 'SERVER_SIDE_ENCRYPTED',
          'cost_configured': true,
          'recommended_price_below_cost': true,
        },
      );
      await tester.pumpWidget(
        _dialogHost(
          onPressed: (context) async {
            decision = await showRecommendationDecisionDialog(
              context,
              recommendation: recommendation,
              decision: 'accepted',
            );
          },
        ),
      );

      await tester.tap(find.text('Open'));
      await tester.pumpAndSettle();
      expect(
        find.textContaining('ниже сохранённой себестоимости'),
        findsOneWidget,
      );
      expect(
        find.textContaining('Исходная себестоимость не возвращается'),
        findsOneWidget,
      );

      await tester.tap(find.text('Записать'));
      await tester.pumpAndSettle();
      expect(
        find.textContaining('Подтвердите ручное решение ниже'),
        findsOneWidget,
      );
      expect(decision, isNull);

      await tester.tap(
        find.text('Разрешаю ручное решение ниже зашифрованной себестоимости'),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('Записать'));
      await tester.pumpAndSettle();

      expect(decision?['allow_below_cost'], isTrue);
      expect(decision?['warning_confirmed'], isTrue);
      expect(decision?.containsKey('cost'), isFalse);
    },
  );
}

Widget _dialogHost({
  required Future<void> Function(BuildContext context) onPressed,
}) {
  return MaterialApp(
    theme: AppTheme.light,
    home: Scaffold(
      body: Builder(
        builder: (context) => FilledButton(
          onPressed: () => onPressed(context),
          child: const Text('Open'),
        ),
      ),
    ),
  );
}

PricingRecommendation _recommendation({required Map<String, dynamic> context}) {
  return PricingRecommendation.fromJson({
    'id': 'rec-encrypted-cost',
    'pricing_run_id': 'run-1',
    'catalog_snapshot_id': 'snapshot-1',
    'catalog_item_id': 'item-1',
    'sku': 'SKU-1',
    'oe_norm': 'OE-1',
    'name': 'Dead-stock part',
    'category': 'Parts',
    'stock_status': 'dead_stock',
    'context_snapshot': context,
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
    'computed_at': '2026-07-18T12:00:00Z',
  });
}
