import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/features/stores/store_models.dart';

void main() {
  test('parses store and product API models', () {
    final store = StoreSummary.fromJson({
      'id': 'store-id',
      'marketplace': 'prom',
      'external_id': '2847093',
      'name': 'kemp',
      'url': 'https://prom.ua/ua/c2847093-kemp.html',
      'kind': 'owned',
      'product_count': 12,
      'last_synced_at': '2026-07-13T12:00:00Z',
    });
    final product = StoreProduct.fromJson({
      'id': 'product-id',
      'name': 'Product',
      'url': 'https://prom.ua/ua/p1-product.html',
      'sku': 'SKU-1',
      'brand': 'Brand',
      'current_price': '123.45',
      'currency': 'UAH',
      'is_available': true,
    });

    expect(store.productCount, 12);
    expect(store.lastSyncedAt, isNotNull);
    expect(store.displayName, 'kemp');
    expect(product.price, 123.45);
    expect(product.isAvailable, isTrue);
    expect(product.priceLabel, '123.45 UAH');
    expect(product.details, 'Brand · SKU SKU-1 · В наличии');
  });
}
