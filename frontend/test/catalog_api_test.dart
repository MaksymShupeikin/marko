import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/features/catalog/catalog_api.dart';

void main() {
  test('loads the catalog and sends search plus store filters', () async {
    final api = CatalogApi(
      ApiClient(
        client: MockClient((request) async {
          expect(request.method, 'GET');
          expect(request.url.path, '/api/v1/catalog/products');
          expect(request.url.queryParameters['q'], '03-31 402 053');
          expect(request.url.queryParameters['store_id'], 'store-b');
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

    final page = await api.listProducts(
      query: '03-31 402 053',
      storeId: 'store-b',
    );

    expect(page.items, hasLength(1));
    expect(page.items.single.stores, hasLength(2));
    expect(page.items.single.listingCount, 3);
    expect(page.items.single.recommendedPrice, 700);
    expect(page.items.single.recommendationAction, 'RAISE');
    expect(page.duplicatesRemoved, 1);
    expect(page.stores.map((store) => store.name), ['Parts Avto', 'ПРОФПАРТС']);
  });

  test(
    'loads only competitor evidence for the selected catalog product',
    () async {
      final api = CatalogApi(
        ApiClient(
          client: MockClient((request) async {
            expect(request.method, 'GET');
            expect(request.url.path, '/api/v1/catalog/competitors');
            expect(request.url.queryParameters['sku'], '0331402053');
            expect(request.url.queryParameters['oe'], '6 1131 36 9611');
            expect(request.url.queryParameters['brand'], 'KEMP');
            return http.Response.bytes(
              utf8.encode(
                jsonEncode({
                  'recommendation_id': 'recommendation-id',
                  'compared_at': '2026-07-25T13:00:00Z',
                  'current_price': '720.00',
                  'fair_price': '690.00',
                  'recommended_price': '700.00',
                  'currency': 'UAH',
                  'reason_codes': <String>[],
                  'items': [
                    {
                      'observation_id': 'observation-id',
                      'seller_id': 'auto-partner',
                      'seller_name': 'Auto Partner',
                      'title': 'Реле стартера Bosch для Mercedes',
                      'url': 'https://prom.ua/ua/p-competitor.html',
                      'price': '680.00',
                      'currency': 'UAH',
                      'is_available': true,
                      'normalized_price': '690.00',
                      'tier': 'aftermarket_a',
                      'match_confidence': '0.96',
                      'observed_at': '2026-07-25T12:00:00Z',
                    },
                  ],
                }),
              ),
              200,
              headers: {'content-type': 'application/json; charset=utf-8'},
            );
          }),
          baseUrl: 'http://api.test',
        ),
      );

      final comparison = await api.listCompetitors(
        sku: '0331402053',
        oe: '6 1131 36 9611',
        brand: 'KEMP',
      );

      expect(comparison.items, hasLength(1));
      expect(comparison.items.single.sellerName, 'Auto Partner');
      expect(comparison.items.single.price, 680);
      expect(comparison.items.single.normalizedPrice, 690);
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
      'recommended_price': '700.00',
      'recommendation_currency': 'UAH',
      'recommendation_action': 'RAISE',
      'recommendation_computed_at': '2026-07-25T13:00:00Z',
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
  'stores': [
    {'store_id': 'store-a', 'external_id': '3912822', 'name': 'Parts Avto'},
    {'store_id': 'store-b', 'external_id': '3325174', 'name': 'ПРОФПАРТС'},
  ],
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
