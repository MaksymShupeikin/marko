import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/features/dashboard/dashboard_page.dart';
import 'package:marko_client/features/products/products_api.dart';

const _searchPayload = {
  'query': 'W914/2',
  'title': 'Mann-Filter W 9142',
  'brand': 'Mann-Filter',
  'is_original': false,
  'part_url': 'https://avto.pro/part-W9142-MANN-79/',
  'offers_total': 2,
  'min_price': 100.91,
  'median_price': 181.96,
  'max_price': 263.0,
  'offers': [
    {
      'maker': 'Shafer',
      'code': 'FOM384',
      'description': 'Фильтр масляный',
      'city': 'Киев',
      'availability': 'В наличии',
      'price': 100.91,
      'currency': 'UAH',
      'boosted': true,
    },
    {
      'maker': 'Mann-Filter',
      'code': 'W9142',
      'description': 'Фильтр масляный',
      'city': 'Днепр',
      'availability': 'В наличии',
      'price': 263.0,
      'currency': 'UAH',
      'boosted': false,
    },
  ],
};

ApiClient _clientWith(MockClientHandler handler) {
  return ApiClient(client: MockClient(handler), baseUrl: 'http://api.test');
}

ProductsApi _apiWith(MockClientHandler handler) =>
    ProductsApi(_clientWith(handler));

void main() {
  test(
    'searchCompetitors queries avto.pro endpoint and parses stats',
    () async {
      final api = _apiWith((request) async {
        expect(request.url.path, '/api/v1/competitors/avtopro');
        expect(request.url.queryParameters, {'oem': 'W914/2', 'brand': 'MANN'});
        return http.Response(
          jsonEncode(_searchPayload),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      });

      final result = await api.searchCompetitors('W914/2', brand: 'MANN');

      expect(result.title, 'Mann-Filter W 9142');
      expect(result.minPrice, 100.91);
      expect(result.offers, hasLength(2));
      expect(result.offers.first.partLabel, 'Shafer FOM384');
    },
  );

  testWidgets('the OEM lookup searches avto.pro without touching the catalog', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);

    final client = _clientWith((request) async {
      final body = switch (request.url.path) {
        '/api/v1/stores' => jsonEncode([]),
        '/api/v1/products' => jsonEncode({
          'items': [
            {
              'id': 'product-1',
              'name': 'Фільтр масляний Mann-Filter',
              'url': 'https://prom.ua/product-1',
              'sku': 'W914/2',
              'brand': 'Mann-Filter',
              'current_price': '101.0',
              'currency': 'UAH',
              'is_available': true,
              'image_url': null,
            },
          ],
          'total': 1,
          'limit': 60,
          'offset': 0,
        }),
        '/api/v1/competitors/avtopro' => jsonEncode(_searchPayload),
        _ => '{}',
      };
      return http.Response(
        body,
        200,
        headers: {'content-type': 'application/json; charset=utf-8'},
      );
    });

    await tester.pumpWidget(
      ProviderScope(
        overrides: [productsApiProvider.overrideWithValue(ProductsApi(client))],
        child: const MaterialApp(home: DashboardPage()),
      ),
    );
    await tester.pumpAndSettle();

    // TopBar has dedicated competitor prices lookup button
    expect(find.text('Ціни конкурентів'), findsOneWidget);
    await tester.tap(find.text('Ціни конкурентів'));
    await tester.pumpAndSettle();

    expect(find.text('OEM номер або назва'), findsOneWidget);

    await tester.enterText(
      find.widgetWithText(TextField, 'OEM номер або назва'),
      'W914/2',
    );
    await tester.tap(find.text('Знайти ціни'));
    await tester.pumpAndSettle();

    expect(find.text('Mann-Filter W 9142'), findsOneWidget);
    expect(find.text('101 UAH'), findsOneWidget);
    expect(find.text('Мінімум'), findsOneWidget);

    // "Приклади:" label is removed
    expect(find.text('Приклади:'), findsNothing);

    // History section contains the recent query
    expect(find.text('Нещодавні пошуки'), findsOneWidget);
  });
}
