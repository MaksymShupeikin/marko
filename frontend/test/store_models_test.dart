import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/features/products/products_models.dart';

void main() {
  test('parses product, import, and competitor models', () {
    final product = StoreProduct.fromJson({
      'id': 'product-id',
      'name': 'Product',
      'url': 'https://prom.ua/ua/p1-product.html',
      'sku': 'SKU-1',
      'brand': 'Brand',
      'current_price': '123.45',
      'currency': 'UAH',
      'is_available': true,
      'image_url': 'https://images.prom.ua/product.jpg',
      'store_id': 'store-1',
      'store_name': 'KEMP',
      'oem_numbers': ['701807101'],
      'group_size': 2,
      'siblings': [
        {
          'listing_id': 'product-2',
          'store_id': 'store-2',
          'store_name': 'Avtobust',
          'current_price': '150.00',
          'currency': 'UAH',
          'is_available': false,
          'url': 'https://prom.ua/ua/p2-product.html',
        },
      ],
    });

    final fileImport = FileImportResult.fromJson({
      'store_id': 's1',
      'store_name': 'MyStore',
      'imported': 50,
      'skipped': 2,
    });

    final competitor = CompetitorPriceReport.fromJson({
      'cached': false,
      'observed_at': '2026-08-23T12:00:00Z',
      'stats': {
        'offers_total': 15,
        'eligible_offers_total': 3,
        'sources_total': 2,
        'min_price': '100.00',
        'median_price': '150.00',
        'max_price': '200.00',
      },
      'sources': [
        {
          'source': 'avtopro',
          'label': 'Avto.pro',
          'status': 'ok',
          'offers_total': 1,
          'min_price': '100.00',
          'offers': [
            {
              'source': 'avtopro',
              'title': 'VW 701807101 Бампер',
              'price': '100.00',
              'currency': 'UAH',
              'url': 'https://avto.pro/part-701807101',
              'city': 'Kyiv',
              'is_analog': false,
            },
          ],
        },
      ],
    });

    expect(product.price, 123.45);
    expect(product.isAvailable, isTrue);
    expect(product.imageUrl, 'https://images.prom.ua/product.jpg');
    expect(product.priceLabel, '123.45 UAH');
    expect(product.details, 'Brand · SKU SKU-1 · В наявності');
    expect(product.primaryOem, '701807101');
    expect(product.storeId, 'store-1');
    expect(product.groupSize, 2);
    expect(product.isGrouped, isTrue);
    expect(product.storeGroupLabel, 'у 2 магазинах');
    expect(product.siblings.single.storeName, 'Avtobust');
    expect(product.allOwnCopies.map((copy) => copy.listingId), [
      'product-id',
      'product-2',
    ]);

    final refreshed = StoreProduct.fromJson({
      'id': 'product-id',
      'name': 'Refreshed',
      'url': 'https://prom.ua/ua/p1-product.html',
      'sku': 'SKU-1',
      'brand': 'Brand',
      'current_price': '125.00',
      'currency': 'UAH',
      'is_available': true,
      'image_url': null,
      'store_id': 'store-1',
    }).withGroupingFrom(product);
    expect(refreshed.name, 'Refreshed');
    expect(refreshed.price, 125);
    expect(refreshed.groupSize, 2);
    expect(refreshed.siblings.single.listingId, 'product-2');

    expect(fileImport.imported, 50);
    expect(fileImport.summary, contains('50 товарів'));

    expect(competitor.stats.offersTotal, 15);
    expect(competitor.stats.eligibleOffersTotal, 3);
    expect(competitor.stats.minPrice, 100.0);
    expect(competitor.currency, 'UAH');
    expect(competitor.sources.first.offers.first.title, 'VW 701807101 Бампер');
  });
}
