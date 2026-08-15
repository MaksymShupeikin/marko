import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/pricing/pricing_models.dart';
import 'package:marko_client/features/pricing/recommendations_page.dart';

void main() {
  testWidgets(
    'gated budget-floor target is explicit and never presented as auto price',
    (tester) async {
      final recommendation = PricingRecommendation.fromJson({
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
            'excluded_implausible_count': 1,
            'plausibility_floor': '420',
          },
          'advisory_decision': {
            'status': 'COMPARABILITY_REVIEW_REQUIRED',
            'action': 'LOWER',
            'recommended_price': '950',
            'minimum_comparable_price': '1000',
            'target_band_low': '950',
            'target_band_high': '950',
            'automatic_price_application': false,
          },
        },
        'action': 'MANUAL_REVIEW',
        'current_price': '1200',
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
        'currency': 'UAH',
        'price_tick': '1.0000',
        'price_tick_version': 'uah-integer-v1',
        'computed_at': '2026-07-30T12:00:00Z',
      });

      expect(recommendation.priceTickScale, 0);
      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.light,
          home: Scaffold(
            body: CustomerPriceAdvisory(recommendation: recommendation),
          ),
        ),
      );

      expect(
        find.byKey(const ValueKey('customer-price-advisory')),
        findsOneWidget,
      );
      expect(find.text('Ценовой ориентир заказчика'), findsOneWidget);
      expect(find.textContaining('Снизить: 950 UAH'), findsOneWidget);
      expect(
        find.textContaining('Минимальная сопоставимая цена: 1000 UAH'),
        findsOneWidget,
      );
      expect(
        find.textContaining('Формула: минимальная подтверждённая цена'),
        findsOneWidget,
      );
      expect(
        find.textContaining('учтите закупку, комиссию Prom'),
        findsOneWidget,
      );
      expect(
        find.textContaining(
          'исключено подозрительно дешёвых предложений: 1 (ниже 420 UAH)',
        ),
        findsOneWidget,
      );
      expect(
        find.textContaining('автоматически не применяется'),
        findsOneWidget,
      );
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'incomplete-evidence advisory shows the number and is not auto price',
    (tester) async {
      final recommendation = PricingRecommendation.fromJson({
        'id': 'recommendation-id',
        'pricing_run_id': 'run-id',
        'catalog_item_id': 'item-id',
        'sku': '1153724258',
        'oe_norm': '578128',
        'name': 'Part',
        'category': 'Parts',
        'stock_status': 'dead_stock',
        'calculation_trace': {
          'customer_pricing_policy': {
            'strategy': 'budget_floor',
            'minimum_discount': '0.05',
            'maximum_discount': '0.05',
            'automatic_price_application': false,
          },
          'advisory_decision': {
            'status': 'INCOMPLETE_EVIDENCE_REVIEW_REQUIRED',
            'action': 'RAISE',
            'recommended_price': '702',
            'minimum_comparable_price': '739',
            'target_band_low': '702',
            'target_band_high': '702',
            'automatic_price_application': false,
            'reason': 'ADVISORY_FROM_UNVERIFIED_VISIBLE_OFFERS',
            'basis_offer_count': 7,
            'basis_independent_sellers': 6,
            'check_package_unit': true,
          },
        },
        'action': 'INSUFFICIENT_DATA',
        'current_price': '679',
        'fair_price': null,
        'recommended_price': null,
        'confidence': '0',
        'confidence_grade': 'MANUAL',
        'weakest_factor': 'coverage',
        'factor_scores': <String, dynamic>{},
        'competitor_count': 0,
        'priority_score': '0',
        'priority_score_type': 'none',
        'review_priority': '0',
        'reason_codes': ['TOO_FEW_COMPETITORS'],
        'currency': 'UAH',
        'price_tick': '1.0000',
        'price_tick_version': 'uah-integer-v1',
        'computed_at': '2026-08-13T12:00:00Z',
      });

      expect(recommendation.hasAdvisoryPrice, isTrue);
      expect(recommendation.recommendedPrice, isNull);
      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.light,
          home: Scaffold(
            body: CustomerPriceAdvisory(recommendation: recommendation),
          ),
        ),
      );

      expect(
        find.byKey(const ValueKey('customer-price-advisory')),
        findsOneWidget,
      );
      expect(
        find.textContaining('Не подтверждено автоматически'),
        findsOneWidget,
      );
      expect(find.textContaining('Поднять: 702 UAH'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
}
