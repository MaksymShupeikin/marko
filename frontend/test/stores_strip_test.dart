import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/products/products_api.dart';
import 'package:marko_client/features/products/widgets/stores_strip.dart';

List<Map<String, dynamic>> _mockStoresJson() => [
      {
        'id': 'store-1',
        'name': 'Kemp Auto',
        'url': 'https://kemp.prom.ua',
        'logo_url': null,
        'product_count': 142,
        'created_at': '2026-08-01T10:00:00Z',
      },
      {
        'id': 'store-2',
        'name': 'Brembo Parts',
        'url': 'https://brembo.prom.ua',
        'logo_url': null,
        'product_count': 58,
        'created_at': '2026-08-02T10:00:00Z',
      },
      {
        'id': 'store-3',
        'name': 'Bosch Service',
        'url': 'https://bosch.prom.ua',
        'logo_url': null,
        'product_count': 94,
        'created_at': '2026-08-03T10:00:00Z',
      },
    ];

Widget _app({
  List<Map<String, dynamic>>? stores,
}) {
  final client = ApiClient(
    client: MockClient((request) async {
      if (request.url.path == '/api/v1/stores') {
        return http.Response(
          jsonEncode(stores ?? _mockStoresJson()),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }
      if (request.url.path == '/api/v1/products') {
        return http.Response(
          jsonEncode({
            'items': [],
            'total': 0,
            'limit': 60,
            'offset': 0,
          }),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }
      return http.Response('{}', 200);
    }),
    baseUrl: 'http://api.test',
  );

  return ProviderScope(
    overrides: [
      productsApiProvider.overrideWithValue(ProductsApi(client)),
    ],
    child: MaterialApp(
      theme: AppTheme.light,
      home: const Scaffold(
        body: SingleChildScrollView(
          child: StoresStrip(),
        ),
      ),
    ),
  );
}

void main() {
  testWidgets('renders horizontal stores scroll list with titles and counts', (
    tester,
  ) async {
    // Phone viewport: 390x844
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(() {
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });

    await tester.pumpWidget(_app());
    await tester.pumpAndSettle();

    expect(find.text('Магазини'), findsOneWidget);
    expect(find.text('3'), findsOneWidget); // Store count badge
    expect(find.text('Kemp Auto'), findsOneWidget);
    expect(find.text('Brembo Parts'), findsOneWidget);
    expect(find.text('142 товари'), findsOneWidget);
    expect(find.text('58 товарів'), findsOneWidget);

    // Verify horizontal ListView exists and has horizontal scroll direction
    final listViewFinder = find.byType(ListView);
    expect(listViewFinder, findsOneWidget);
    final listView = tester.widget<ListView>(listViewFinder);
    expect(listView.scrollDirection, Axis.horizontal);
  });

  testWidgets('tapping a store toggles filter and shows reset button', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(() {
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });

    await tester.pumpWidget(_app());
    await tester.pumpAndSettle();

    // Initially no reset button
    expect(find.text('Скинути'), findsNothing);

    // Tap on Kemp Auto
    await tester.tap(find.text('Kemp Auto'));
    await tester.pumpAndSettle();

    // Reset button appears
    expect(find.text('Скинути'), findsOneWidget);

    // Tap Reset
    await tester.tap(find.text('Скинути'));
    await tester.pumpAndSettle();

    expect(find.text('Скинути'), findsNothing);
  });

  testWidgets('renders nothing if stores list is empty', (tester) async {
    await tester.pumpWidget(_app(stores: []));
    await tester.pumpAndSettle();

    expect(find.text('Магазини'), findsNothing);
    expect(find.byType(ListView), findsNothing);
  });
}
