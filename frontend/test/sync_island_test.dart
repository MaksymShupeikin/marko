import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/products/products_api.dart';
import 'package:marko_client/features/products/products_page.dart';
import 'package:marko_client/features/products/widgets/product_card.dart';
import 'package:marko_client/features/products/widgets/source_panel.dart';

/// A catalog that starts empty and grows once the sync reports progress, plus
/// a job that runs, then completes.
class _Backend {
  int products = 0;
  final jobs = <Map<String, dynamic>>[
    {'status': 'running', 'progress_current': 2, 'progress_total': 4},
    {'status': 'completed', 'progress_current': 4, 'progress_total': 4},
  ];

  ApiClient client() {
    return ApiClient(
      client: MockClient((request) async {
        final body = switch (request.url.path) {
          '/api/v1/products' => jsonEncode({
            'items': [
              for (var i = 0; i < products; i++)
                {
                  'id': 'p$i',
                  'name': 'Товар $i',
                  'url': 'https://x.prom.ua/p$i.html',
                  'sku': 'SKU-$i',
                  'brand': 'KEMP',
                  'currency': 'UAH',
                  'current_price': 100,
                  'is_available': true,
                  'image_url': null,
                  'oem_numbers': const [],
                  'can_manage': true,
                },
            ],
            'total': products,
            'limit': 60,
            'offset': 0,
          }),
          '/api/v1/stores' => jsonEncode({
            'store_id': 's1',
            'sync_run_id': 'run-1',
            'status': 'queued',
          }),
          '/api/v1/jobs/run-1' => () {
            products += 2;
            return jsonEncode(jobs.removeAt(0));
          }(),
          _ => '{}',
        };
        return http.Response(
          body,
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }),
      baseUrl: 'http://api.test',
    );
  }
}

Widget _app(ApiClient client) => ProviderScope(
  overrides: [productsApiProvider.overrideWithValue(ProductsApi(client))],
  child: MaterialApp(
    theme: AppTheme.light,
    home: const Scaffold(body: ProductsPage()),
  ),
);

void main() {
  setUp(() {
    final view = TestWidgetsFlutterBinding.ensureInitialized()
        .platformDispatcher
        .views
        .first;
    view.physicalSize = const Size(1400, 1800);
    view.devicePixelRatio = 1;
  });

  tearDown(() {
    final view = TestWidgetsFlutterBinding.ensureInitialized()
        .platformDispatcher
        .views
        .first;
    view.resetPhysicalSize();
    view.resetDevicePixelRatio();
  });

  testWidgets('a running sync shows the island, streams products, then goes', (
    tester,
  ) async {
    await tester.pumpWidget(_app(_Backend().client()));
    await tester.pumpAndSettle();

    // Порожній каталог — онбординг, ані капсули, ані скелетонів.
    expect(
      find.text('Додайте товари з XLSX-вивантаження'),
      findsOneWidget,
    );
    expect(find.byType(ProductCardSkeleton), findsNothing);

    await tester.enterText(
      find.byType(TextField).first,
      'https://prom.ua/c1-shop.html',
    );
    await tester.tap(find.text('Імпортувати каталог').first);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));

    // Онбординг поступився каталогу: капсула зверху, привиди в сітці.
    expect(find.text('Синхронізація Prom.ua'), findsOneWidget);
    expect(
      find.text('Додайте товари з XLSX-вивантаження'),
      findsNothing,
    );
    expect(find.byType(ProductCardSkeleton), findsWidgets);
    expect(find.text('Товар 0'), findsOneWidget);

    // Другий опит завершує роботу: підсумок, потім капсула зникає сама.
    await tester.pump(const Duration(seconds: 2));
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.text('Каталог оновлено'), findsOneWidget);
    expect(find.byType(ProductCardSkeleton), findsNothing);
    expect(find.text('Товар 3'), findsOneWidget);

    await tester.pump(const Duration(seconds: 5));
    await tester.pumpAndSettle();
    expect(find.text('Каталог оновлено'), findsNothing);
  });

  testWidgets('the sync panel no longer duplicates the progress inline', (
    tester,
  ) async {
    await tester.pumpWidget(_app(_Backend().client()));
    await tester.pumpAndSettle();

    expect(find.byType(SourcePanel), findsOneWidget);
    expect(find.textContaining('Імпорт каталогу:'), findsNothing);
  });
}
