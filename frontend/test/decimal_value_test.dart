import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/presentation_formatters.dart';
import 'package:marko_client/features/pricing/pricing_models.dart';
import 'package:marko_client/features/stores/store_models.dart';

void main() {
  test('DecimalValue preserves digits beyond binary-double precision', () {
    final value = DecimalValue.parse('9007199254740993.010000000000000001');

    expect(value.toString(), '9007199254740993.010000000000000001');
    expect(jsonEncode({'price': value}), '{"price":"${value.toString()}"}');
  });

  test('DecimalValue performs exact base-10 money arithmetic', () {
    final tenth = DecimalValue.parse('0.1');

    expect(tenth * 3, DecimalValue.parse('0.3'));
    expect(
      DecimalValue.parse(
        '1234.567',
      ).roundToMultiple(DecimalValue.parse('0.50')),
      DecimalValue.parse('1234.50'),
    );
  });

  test('pricing and store models retain server decimal strings', () {
    final recommendation = PricingRecommendation.fromJson({
      'id': 'rec',
      'pricing_run_id': 'run',
      'catalog_item_id': 'item',
      'sku': 'SKU',
      'oe_norm': 'OE',
      'name': 'Part',
      'category': 'parts',
      'stock_status': 'fresh',
      'action': 'RAISE',
      'current_price': '9007199254740993.01',
      'recommended_price': '9007199254740993.02',
      'confidence': '0.8',
      'confidence_grade': 'A',
      'competitor_count': 3,
      'priority_score': '0',
      'priority_score_type': 'none',
      'reason_codes': <String>[],
      'currency': 'UAH',
      'price_tick': '0.01',
      'computed_at': '2026-07-30T00:00:00Z',
    });
    final product = StoreProduct.fromJson({
      'id': 'product',
      'name': 'Part',
      'url': 'https://example.test',
      'sku': 'SKU',
      'brand': 'Brand',
      'current_price': '9007199254740993.01',
      'currency': 'UAH',
      'is_available': true,
      'image_url': null,
    });

    expect(recommendation.currentPrice.toString(), '9007199254740993.01');
    expect(recommendation.recommendedPrice.toString(), '9007199254740993.02');
    expect(product.price.toString(), '9007199254740993.01');
  });
}
