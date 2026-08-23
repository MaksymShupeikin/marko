import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/features/products/products_api.dart';
import 'package:marko_client/features/products/products_models.dart';

Map<String, dynamic> _productJson({String name = 'Фільтр'}) => {
  'id': 'product-1',
  'external_id': 'prom-1',
  'name': name,
  'url': 'https://prom.ua/p1.html',
  'sku': 'SKU-1',
  'model_id': null,
  'brand': 'Bosch',
  'currency': 'UAH',
  'current_price': 125.5,
  'is_available': true,
  'image_url': null,
  'last_seen_at': '2026-08-22T10:00:00Z',
  'store_id': 'store-1',
  'store_name': 'Мій магазин',
  'marketplace': 'prom',
  'oem_numbers': ['OEM-1'],
  'can_manage': true,
};

void main() {
  test('updates a product with PATCH and parses the result', () async {
    final api = ProductsApi(
      ApiClient(
        client: MockClient((request) async {
          expect(request.method, 'PATCH');
          expect(request.url.path, '/api/v1/products/product-1');
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          expect(body['name'], 'Новий фільтр');
          expect(body['current_price'], 125.5);
          expect(body['oem_numbers'], ['OEM-1']);
          return http.Response.bytes(
            utf8.encode(jsonEncode(_productJson(name: 'Новий фільтр'))),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }),
        baseUrl: 'http://api.test',
      ),
    );

    final updated = await api.updateProduct(
      'product-1',
      const ProductUpdate(
        name: 'Новий фільтр',
        sku: 'SKU-1',
        brand: 'Bosch',
        price: 125.5,
        isAvailable: true,
        imageUrl: null,
        oemNumbers: ['OEM-1'],
      ),
    );

    expect(updated.name, 'Новий фільтр');
    expect(updated.canManage, isTrue);
  });

  test('deletes a product with DELETE', () async {
    final api = ProductsApi(
      ApiClient(
        client: MockClient((request) async {
          expect(request.method, 'DELETE');
          expect(request.url.path, '/api/v1/products/product-1');
          return http.Response('', 204);
        }),
        baseUrl: 'http://api.test',
      ),
    );

    await api.deleteProduct('product-1');
  });
}
