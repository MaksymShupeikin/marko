import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/features/dashboard/dashboard_page.dart';
import 'package:marko_client/features/products/products_api.dart';

const _report = {
  'cached': false,
  'observed_at': '2026-08-23T12:00:00Z',
  'stats': {
    'offers_total': 2,
    'eligible_offers_total': 2,
    'sources_total': 2,
    'min_price': '100.91',
    'median_price': '181.96',
    'max_price': '263.00',
  },
  'sources': [
    {
      'source': 'avtopro',
      'label': 'Avto.pro',
      'status': 'ok',
      'offers_total': 2,
      'min_price': '100.91',
      'median_price': '181.96',
      'max_price': '263.00',
      'offers': [
        {
          'source': 'avtopro',
          'title': 'Shafer FOM384 Фильтр масляный',
          'price': '100.91',
          'currency': 'UAH',
          'url': 'https://avto.pro/part-FOM384',
          'city': 'Киев',
          'is_analog': true,
        },
        {
          'source': 'avtopro',
          'title': 'Mann-Filter W9142 Фильтр масляный',
          'price': '263.00',
          'currency': 'UAH',
          'url': 'https://avto.pro/part-W9142',
          'city': 'Днепр',
          'is_analog': false,
        },
      ],
    },
  ],
};

/// Потік подій так, як його віддає бекенд: стадії, потім готовий звіт.
String _sse() => [
  '{"stage":"source","message":"Збираємо пропозиції: Avto.pro"}',
  '{"stage":"done","report":${jsonEncode(_report)}}',
].map((event) => 'data: $event\n\n').join();

ApiClient _clientWith(MockClientHandler handler) {
  return ApiClient(client: MockClient(handler), baseUrl: 'http://api.test');
}

ProductsApi _apiWith(MockClientHandler handler) =>
    ProductsApi(_clientWith(handler));

void main() {
  test('competitorSearchEvents streams stages then the finished report', () async {
    final api = _apiWith((request) async {
      expect(request.url.path, '/api/v1/competitors/search/stream');
      expect(request.url.queryParameters, {'oem': 'W914/2', 'brand': 'MANN'});
      return http.Response(
        _sse(),
        200,
        headers: {'content-type': 'text/event-stream; charset=utf-8'},
      );
    });

    final events = await api
        .competitorSearchEvents('W914/2', brand: 'MANN')
        .toList();

    expect(events, hasLength(2));
    expect(events.first['stage'], 'source');
    expect(events.first['message'], contains('Avto.pro'));
    expect(events.last['stage'], 'done');
    expect(events.last['report']['stats']['offers_total'], 2);
  });

  testWidgets('the OEM lookup runs the shared pipeline without touching the catalog', (
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
        '/api/v1/competitors/search/stream' => _sse(),
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
    // Потік читається через справжній event loop, тож pump його не прокручує.
    await tester.runAsync(() => Future<void>.delayed(Duration.zero));
    for (var i = 0; i < 10; i++) {
      await tester.pump(const Duration(milliseconds: 50));
    }
    expect(find.text('Знайдено на ринку'), findsOneWidget);
    expect(find.text('Avto.pro: 2'), findsOneWidget);
    // Пропозиції з обох джерел в одній ціновій драбині, аналог позначено.
    expect(find.text('Shafer FOM384 Фильтр масляный'), findsOneWidget);
    expect(find.text('аналог'), findsOneWidget);
    expect(find.text('Мінімум'), findsOneWidget);

    // History section contains the recent query
    expect(find.text('Останні пошуки'), findsOneWidget);
  });
}
