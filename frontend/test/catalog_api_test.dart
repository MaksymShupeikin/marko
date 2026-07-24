import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/features/catalog/catalog_api.dart';

void main() {
  test(
    'loads the deduplicated owned-store catalog and sends OE query',
    () async {
      final api = CatalogApi(
        ApiClient(
          client: MockClient((request) async {
            expect(request.method, 'GET');
            expect(request.url.path, '/api/v1/catalog/products');
            expect(request.url.queryParameters['q'], '03-31 402 053');
            expect(request.url.queryParameters['limit'], '48');
            return http.Response.bytes(
              utf8.encode(jsonEncode(_pageJson())),
              200,
              headers: {'content-type': 'application/json; charset=utf-8'},
            );
          }),
          baseUrl: 'http://api.test',
        ),
      );

      final page = await api.listProducts(query: '03-31 402 053');

      expect(page.items, hasLength(1));
      expect(page.items.single.stores, hasLength(2));
      expect(page.items.single.listingCount, 3);
      expect(page.duplicatesRemoved, 1);
    },
  );
}

Map<String, dynamic> _pageJson() => {
  'items': [
    {
      'id': 'product-id',
      'identity_kind': 'brand_sku',
      'name': 'Втягивающее реле стартера Mercedes',
      'sku': '0331402053',
      'oe': null,
      'model_id': null,
      'brand': 'KEMP',
      'image_url': 'https://images.prom.ua/product.jpg',
      'price_min': '420.00',
      'price_max': '450.00',
      'currency': 'UAH',
      'listing_count': 3,
      'stores': [
        _storeJson('store-a', '3912822', 'parts-avto', 2, '420.00'),
        _storeJson('store-b', '3325174', 'profparts', 1, '450.00'),
      ],
    },
  ],
  'total': 1,
  'catalog_total': 2,
  'listing_total': 3,
  'duplicates_removed': 1,
  'store_total': 2,
  'limit': 48,
  'offset': 0,
};

Map<String, dynamic> _storeJson(
  String id,
  String externalId,
  String name,
  int listingCount,
  String price,
) => {
  'store_id': id,
  'external_id': externalId,
  'name': name,
  'url': 'https://prom.ua/ua/c$externalId-$name.html',
  'listing_url': 'https://prom.ua/ua/p1-product.html',
  'listing_count': listingCount,
  'price': price,
  'currency': 'UAH',
  'is_available': true,
};
