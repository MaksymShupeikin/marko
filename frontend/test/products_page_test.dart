import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/core/marko_ui.dart';
import 'package:marko_client/core/widgets/marko_button.dart';
import 'package:marko_client/features/products/products_api.dart';
import 'package:marko_client/features/products/products_page.dart';
import 'package:marko_client/features/products/widgets/catalog_filters.dart';
import 'package:marko_client/features/products/widgets/product_details_panel.dart';
import 'package:marko_client/features/products/widgets/source_panel.dart';
import 'package:toastification/toastification.dart';

/// Toasts live in the root overlay: they outlive the action that raised them,
/// so a test has to clear them before tapping whatever they cover.
Future<void> _clearToasts(WidgetTester tester) async {
  toastification.dismissAll(delayForAnimation: false);
  await tester.pump(const Duration(milliseconds: 700));
  await tester.pumpAndSettle();
}

Map<String, dynamic> _product(
  String id,
  String name, {
  double price = 100,
  List<String> oem = const [],
}) {
  return {
    'id': id,
    'external_id': id,
    'name': name,
    'url': 'https://kemp-cs2847093.prom.ua/p$id-detail.html',
    'sku': 'SKU-$id',
    'model_id': null,
    'brand': 'KEMP',
    'currency': 'UAH',
    'current_price': price,
    'is_available': true,
    'image_url': null,
    'last_seen_at': '2026-08-21T10:00:00Z',
    'store_id': 'store-id',
    'store_name': 'kemp',
    'marketplace': 'prom',
    'oem_numbers': oem,
    'can_manage': true,
  };
}

/// Records the query parameters the catalog endpoint was called with.
class _Recorder {
  final List<Map<String, String>> calls = [];

  ApiClient client() {
    return ApiClient(
      client: MockClient((request) async {
        final body = switch (request.url.path) {
          '/api/v1/products' => () {
            calls.add(request.url.queryParameters);
            return jsonEncode({
              'items': [
                _product(
                  '1',
                  'Радіатор Iveco',
                  price: 3297,
                  oem: const ['93818439', '77643'],
                ),
                _product('2', 'Термостат Ford', price: 185),
              ],
              'total': 2,
              'limit': 60,
              'offset': 0,
            });
          }(),
          '/api/v1/stores' => jsonEncode([]),
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

Widget _app(ApiClient client) {
  return ProviderScope(
    overrides: [productsApiProvider.overrideWithValue(ProductsApi(client))],
    child: MaterialApp(
      theme: AppTheme.light,
      home: const Scaffold(body: ProductsPage()),
    ),
  );
}

Finder _priceField(String text) => find.byWidgetPredicate(
  (widget) =>
      widget is TextField &&
      (widget.decoration?.labelText == text ||
          widget.decoration?.hintText == text),
);

void main() {
  // The page is a long scroll: give the test a desktop-sized window so the
  // toolbar, the grid and the details panel are all laid out at once.
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

  testWidgets('renders the catalog grid with the product count', (
    tester,
  ) async {
    await tester.pumpWidget(_app(_Recorder().client()));
    await tester.pumpAndSettle();

    expect(find.text('Каталог'), findsOneWidget);
    expect(find.text('Радіатор Iveco'), findsOneWidget);
    expect(find.text('Термостат Ford'), findsOneWidget);
  });

  testWidgets('the price range and sorting reach the API', (tester) async {
    final recorder = _Recorder();
    await tester.pumpWidget(_app(recorder.client()));
    await tester.pumpAndSettle();

    expect(recorder.calls.first['sort'], 'name');
    expect(recorder.calls.first.containsKey('price_min'), isFalse);

    await tester.enterText(_priceField('Ціна від'), '100');
    await tester.enterText(_priceField('Ціна до'), '2 000');
    // The fields debounce like the search box.
    await tester.pump(const Duration(milliseconds: 400));
    await tester.pumpAndSettle();
    expect(recorder.calls.last['price_min'], '100.0');
    expect(recorder.calls.last['price_max'], '2000.0');

    await tester.enterText(_priceField('Ціна до'), '2000,5');
    await tester.pump(const Duration(milliseconds: 400));
    await tester.pumpAndSettle();
    expect(recorder.calls.last['price_max'], '2000.5');

    await tester.tap(find.text('За назвою'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Спочатку дорожчі').last);
    await tester.pumpAndSettle();
    expect(recorder.calls.last['sort'], 'price_desc');
  });

  testWidgets('price fields match the search field height and show ₴', (
    tester,
  ) async {
    await tester.pumpWidget(_app(_Recorder().client()));
    await tester.pumpAndSettle();

    final search = tester.getSize(_priceField('Назва, артикул, бренд').first);
    for (final hint in ['Ціна від', 'Ціна до']) {
      final field = _priceField(hint);
      expect(tester.getSize(field).height, search.height);
      final parentField = find.ancestor(
        of: field,
        matching: find.byType(MarkoTextField),
      );
      final currency = find.descendant(
        of: parentField,
        matching: find.text('₴'),
      );
      expect(currency, findsOneWidget);
      expect(
        tester.getCenter(currency).dy,
        moreOrLessEquals(tester.getCenter(field).dy, epsilon: 1),
      );
    }
  });

  testWidgets('tapping a card opens the details panel for that product', (
    tester,
  ) async {
    await tester.pumpWidget(_app(_Recorder().client()));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Радіатор Iveco'));
    await tester.pumpAndSettle();

    Finder inPanel(String text) => find.descendant(
      of: find.byType(ProductDetailsPanel),
      matching: find.text(text),
    );

    expect(inPanel('3 297'), findsOneWidget);
    expect(
      find.descendant(
        of: find.byType(ProductDetailsPanel),
        matching: find.byTooltip('Відкрити на Prom'),
      ),
      findsOneWidget,
    );
    // The best number shows twice: as the search OEM and in the full list.
    expect(inPanel('93818439'), findsNWidgets(2));
    expect(inPanel('77643'), findsOneWidget);
  });

  testWidgets('a product can be refreshed by URL and deleted from its details', (
    tester,
  ) async {
    var savedName = 'Радіатор Iveco';
    var deleted = false;
    Map<String, dynamic> groupedProduct() => {
      ..._product('1', savedName, price: 3500),
      'group_size': 2,
      'siblings': [
        {
          'listing_id': 'copy-2',
          'store_id': 'store-2',
          'store_name': 'Avtobust',
          'current_price': 3700,
          'currency': 'UAH',
          'is_available': true,
          'url': 'https://avtobust.prom.ua/p2-detail.html',
        },
      ],
    };
    final client = ApiClient(
      client: MockClient((request) async {
        if (request.method == 'POST' &&
            request.url.path == '/api/v1/products/1/refresh') {
          savedName = 'Радіатор Iveco Daily (оновлено)';
          return http.Response.bytes(
            utf8.encode(jsonEncode(_product('1', savedName, price: 3500))),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        if (request.method == 'DELETE' &&
            request.url.path == '/api/v1/products/1') {
          deleted = true;
          return http.Response('', 204);
        }
        if (request.url.path == '/api/v1/products/1/competitor-prices') {
          return http.Response.bytes(
            utf8.encode(
              jsonEncode({
                'cached': false,
                'observed_at': '2026-08-22T10:00:00Z',
                'stats': {
                  'offers_total': 0,
                  'sources_total': 0,
                  'min_price': null,
                  'median_price': null,
                  'max_price': null,
                },
                'sources': [],
              }),
            ),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        if (request.url.path == '/api/v1/products') {
          return http.Response.bytes(
            utf8.encode(
              jsonEncode({
                'items': deleted ? [] : [groupedProduct()],
                'total': deleted ? 0 : 1,
                'limit': 60,
                'offset': 0,
              }),
            ),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        return http.Response('{}', 200);
      }),
      baseUrl: 'http://api.test',
    );

    await tester.pumpWidget(_app(client));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Радіатор Iveco'));
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('Оновити дані за посиланням'));
    await tester.pumpAndSettle();

    expect(
      find.descendant(
        of: find.byType(ProductDetailsPanel),
        matching: find.text('Радіатор Iveco Daily (оновлено)'),
      ),
      findsOneWidget,
    );
    // Refresh returns one listing with group defaults; the controller keeps the
    // catalog siblings so the badge and per-store facts do not disappear.
    expect(find.text('Avtobust · 3 700 ₴'), findsOneWidget);

    await _clearToasts(tester);
    await tester.tap(find.byTooltip('Видалити товар'));
    await tester.pumpAndSettle();
    expect(find.text('Видалити товар?'), findsOneWidget);
    await tester.tap(find.widgetWithText(MarkoButton, 'Видалити'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));

    expect(deleted, isTrue);
    expect(find.byType(ProductDetailsPanel), findsNothing);
    await _clearToasts(tester);
  });

  testWidgets(
    'tapping a card on mobile opens full-screen details with back arrow',
    (tester) async {
      tester.view.physicalSize = const Size(390, 844);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);

      await tester.pumpWidget(_app(_Recorder().client()));
      await tester.pumpAndSettle();

      await tester.tap(find.text('Радіатор Iveco'));
      await tester.pumpAndSettle();

      // On mobile, back arrow icon is shown on the left
      expect(find.byTooltip('Назад'), findsOneWidget);
      expect(
        find.descendant(
          of: find.byType(ProductDetailsPanel),
          matching: find.text('3 297'),
        ),
        findsOneWidget,
      );

      // Tapping back closes the details panel
      await tester.tap(find.byTooltip('Назад'));
      await tester.pumpAndSettle();

      expect(find.byType(ProductDetailsPanel), findsNothing);
    },
  );

  testWidgets('the import sources live in a modal, not on the page', (
    tester,
  ) async {
    await tester.pumpWidget(_app(_Recorder().client()));
    await tester.pumpAndSettle();

    expect(find.text('XLSX вивантаження'), findsNothing);

    // Not awaited: the future only completes once the modal is dismissed.
    unawaited(showCatalogImport(tester.element(find.byType(ProductsPage))));
    await tester.pumpAndSettle();

    expect(find.text('XLSX вивантаження'), findsOneWidget);
    expect(find.text('Магазин Prom.ua'), findsOneWidget);
  });

  testWidgets('the scroll-to-top button appears when scrolled and returns', (
    tester,
  ) async {
    final view = TestWidgetsFlutterBinding.ensureInitialized()
        .platformDispatcher
        .views
        .first;
    view.physicalSize = const Size(900, 260);

    // A long enough catalog to scroll past the button's threshold.
    final client = ApiClient(
      client: MockClient((request) async {
        final body = switch (request.url.path) {
          '/api/v1/products' => jsonEncode({
            'items': [for (var i = 0; i < 24; i++) _product('$i', 'Товар $i')],
            'total': 24,
            'limit': 60,
            'offset': 0,
          }),
          '/api/v1/stores' => jsonEncode([]),
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
    await tester.pumpWidget(_app(client));
    await tester.pumpAndSettle();

    double opacity() => tester
        .widget<AnimatedOpacity>(
          find.ancestor(
            of: find.byTooltip('Вгору'),
            matching: find.byType(AnimatedOpacity),
          ),
        )
        .opacity;
    final scrollable = find.byType(CustomScrollView);
    expect(opacity(), 0);

    await tester.drag(scrollable, const Offset(0, -600));
    await tester.pumpAndSettle();
    expect(opacity(), 1);

    await tester.tap(find.byTooltip('Вгору'));
    await tester.pumpAndSettle();
    expect(
      tester
              .widget<Scrollable>(find.byType(Scrollable).first)
              .controller
              ?.offset ??
          0,
      0,
    );
    expect(opacity(), 0);
  });

  testWidgets('an empty catalog shows onboarding instead of the toolbar', (
    tester,
  ) async {
    final client = ApiClient(
      client: MockClient((request) async {
        final body = switch (request.url.path) {
          '/api/v1/products' => jsonEncode({
            'items': [],
            'total': 0,
            'limit': 60,
            'offset': 0,
          }),
          _ => '[]',
        };
        return http.Response(
          body,
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }),
      baseUrl: 'http://api.test',
    );

    await tester.pumpWidget(_app(client));
    await tester.pumpAndSettle();

    // Instructions plus both source cards, right there — no modal to find.
    expect(
      find.text('Додайте товари з XLSX-вивантаження'),
      findsOneWidget,
    );
    expect(find.text('XLSX вивантаження'), findsOneWidget);
    expect(find.text('Магазин Prom.ua'), findsOneWidget);
    // Nothing to search or sort yet.
    expect(find.text('Каталог'), findsNothing);
    expect(find.byType(CatalogSearchField), findsNothing);
  });

  testWidgets('ticking cards enables bulk refresh and delete', (tester) async {
    final refreshed = <String>[];
    final deleted = <String>[];
    final client = ApiClient(
      client: MockClient((request) async {
        final path = request.url.path;
        if (request.method == 'POST' && path.endsWith('/refresh')) {
          final id = path.split('/')[4];
          refreshed.add(id);
          return http.Response.bytes(
            utf8.encode(jsonEncode(_product(id, 'Оновлено $id', price: 999))),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        if (request.method == 'DELETE' && path.startsWith('/api/v1/products/')) {
          deleted.add(path.split('/').last);
          return http.Response('', 204);
        }
        if (path == '/api/v1/products') {
          return http.Response.bytes(
            utf8.encode(
              jsonEncode({
                'items': [
                  _product('1', 'Радіатор Iveco', price: 3297),
                  _product('2', 'Термостат Ford', price: 185),
                ],
                'total': 2,
                'limit': 60,
                'offset': 0,
              }),
            ),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        return http.Response('{}', 200);
      }),
      baseUrl: 'http://api.test',
    );

    await tester.pumpWidget(_app(client));
    await tester.pumpAndSettle();

    // Позначки з'являються на картках і не чіпають відкриття деталей.
    expect(find.byTooltip('Позначити'), findsNWidgets(2));
    await tester.tap(find.byTooltip('Позначити').first);
    await tester.pumpAndSettle();
    expect(find.text('Вибрано 1'), findsOneWidget);

    await tester.tap(find.byTooltip('Позначити').first);
    await tester.pumpAndSettle();
    expect(find.text('Вибрано 2'), findsOneWidget);

    await tester.tap(find.text('Оновити за посиланням'));
    await tester.pumpAndSettle();
    expect(refreshed, ['1', '2']);
    // Після дії позначки знімаються, панель зникає.
    expect(find.text('Вибрано 2'), findsNothing);
    expect(find.text('Оновлено 1'), findsOneWidget);

    await tester.tap(find.byTooltip('Позначити').first);
    await tester.pumpAndSettle();
    expect(find.text('Вибрано 1'), findsOneWidget);
    await tester.tap(find.text('Скасувати'));
    await tester.pumpAndSettle();
    expect(find.text('Вибрано 1'), findsNothing);

    await tester.tap(find.byTooltip('Позначити').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Видалити'));
    await tester.pumpAndSettle();
    expect(find.text('Видалити товарів: 1?'), findsOneWidget);
    await tester.tap(find.widgetWithText(MarkoButton, 'Видалити'));
    await tester.pumpAndSettle();

    expect(deleted, ['1']);
    expect(find.text('Оновлено 1'), findsNothing);
    await _clearToasts(tester);
  });

  testWidgets('the source toggle filters the catalog and reaches the API', (
    tester,
  ) async {
    final recorder = _Recorder();
    await tester.pumpWidget(_app(recorder.client()));
    await tester.pumpAndSettle();

    expect(recorder.calls.last.containsKey('source'), isFalse);

    await tester.tap(find.text('З файлу'));
    await tester.pumpAndSettle();
    expect(recorder.calls.last['source'], 'export');

    await tester.tap(find.text('З Prom'));
    await tester.pumpAndSettle();
    expect(recorder.calls.last['source'], 'scrape');

    await tester.tap(find.text('Усі'));
    await tester.pumpAndSettle();
    expect(recorder.calls.last.containsKey('source'), isFalse);
  });

  testWidgets('one tick offers acting on the whole catalog, not just the page', (
    tester,
  ) async {
    final bulkCalls = <String>[];
    var deletedAll = false;
    final client = ApiClient(
      client: MockClient((request) async {
        final path = request.url.path;
        if (request.method == 'POST' && path == '/api/v1/products/bulk/refresh') {
          bulkCalls.add(utf8.decode(request.bodyBytes));
          return http.Response(
            jsonEncode({
              'store_id': null,
              'sync_run_id': 'job-1',
              'status': 'queued',
            }),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        if (request.method == 'POST' && path == '/api/v1/products/bulk/delete') {
          deletedAll = true;
          return http.Response(
            jsonEncode({'deleted': 120}),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        if (path == '/api/v1/jobs/job-1') {
          return http.Response(
            jsonEncode({
              'status': 'completed',
              'progress_current': 120,
              'progress_total': 120,
              'error': null,
            }),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        if (path == '/api/v1/products') {
          return http.Response.bytes(
            utf8.encode(
              jsonEncode({
                'items': deletedAll
                    ? []
                    : [
                        _product('1', 'Радіатор Iveco'),
                        _product('2', 'Термостат Ford'),
                      ],
                // Завантажено дві картки, а в каталозі їх 120.
                'total': deletedAll ? 0 : 120,
                'limit': 60,
                'offset': 0,
              }),
            ),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        return http.Response('{}', 200);
      }),
      baseUrl: 'http://api.test',
    );

    await tester.pumpWidget(_app(client));
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('Позначити').first);
    await tester.pumpAndSettle();
    expect(find.text('Вибрано 1'), findsOneWidget);

    await tester.tap(find.text('Усі 120 у каталозі'));
    await tester.pumpAndSettle();
    expect(find.text('Вибрано всі 120'), findsOneWidget);

    // Оновлення йде одним запитом на фільтр, а не 120 запитами на товар.
    await tester.tap(find.text('Оновити за посиланням'));
    await tester.pumpAndSettle();
    expect(bulkCalls, hasLength(1));

    await tester.tap(find.byTooltip('Позначити').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Усі 120 у каталозі'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Видалити'));
    await tester.pumpAndSettle();
    expect(find.text('Видалити товарів: 120?'), findsOneWidget);
    await tester.tap(find.widgetWithText(MarkoButton, 'Видалити'));
    await tester.pumpAndSettle();

    expect(deletedAll, isTrue);
    expect(find.text('Радіатор Iveco'), findsNothing);
    await _clearToasts(tester);
  });
}
