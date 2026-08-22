import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/core/marko_ui.dart';
import 'package:marko_client/features/products/products_api.dart';
import 'package:marko_client/features/products/products_page.dart';
import 'package:marko_client/features/products/widgets/product_details_panel.dart';
import 'package:marko_client/features/products/widgets/source_panel.dart';

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
    child: const MaterialApp(home: ProductsPage()),
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
    expect(inPanel('Відкрити на Prom'), findsOneWidget);
    // The best number shows twice: as the search OEM and in the full list.
    expect(inPanel('93818439'), findsNWidgets(2));
    expect(inPanel('77643'), findsOneWidget);
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
    expect(find.text('Почніть з імпорту каталогу'), findsOneWidget);
    expect(find.text('XLSX вивантаження'), findsOneWidget);
    expect(find.text('Магазин Prom.ua'), findsOneWidget);
    // Nothing to search or sort yet.
    expect(find.text('Каталог'), findsNothing);
    expect(find.byType(CatalogSearchField), findsNothing);
  });
}
