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
      'oem_numbers': ['701807101'],
    });

    final fileImport = FileImportResult.fromJson({
      'store_id': 's1',
      'store_name': 'MyStore',
      'imported': 50,
      'skipped': 2,
    });

    final competitor = CompetitorSearch.fromJson({
      'query': '701807101',
      'title': 'Bumper',
      'is_original': true,
      'part_url': 'https://avto.pro/part-701807101',
      'offers_total': 15,
      'min_price': 100.0,
      'median_price': 150.0,
      'max_price': 200.0,
      'offers': [
        {
          'maker': 'VW',
          'code': '701807101',
          'city': 'Kyiv',
          'price': 100.0,
          'currency': 'UAH',
          'boosted': false,
        },
      ],
    });

    expect(product.price, 123.45);
    expect(product.isAvailable, isTrue);
    expect(product.imageUrl, 'https://images.prom.ua/product.jpg');
    expect(product.priceLabel, '123.45 UAH');
    expect(product.details, 'Brand · SKU SKU-1 · В наявності');
    expect(product.primaryOem, '701807101');

    expect(fileImport.imported, 50);
    expect(fileImport.summary, contains('50 товарів'));

    expect(competitor.offersTotal, 15);
    expect(competitor.offers.first.partLabel, 'VW 701807101');
  });
}
