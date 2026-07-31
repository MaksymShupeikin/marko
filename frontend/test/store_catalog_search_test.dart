import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/stores/store_products_page.dart';
import 'package:marko_client/features/stores/stores_api.dart';
import 'package:marko_client/features/stores/stores_controller.dart';

void main() {
  test(
    'catalog search sends the query to the store products endpoint',
    () async {
      Uri? requested;
      final api = _api((request) async {
        requested = request.url;
        return _json(_productPage([]));
      });

      await api.listProducts('store-id', query: '  77641543  ');

      expect(requested?.path, '/api/v1/stores/store-id/products');
      expect(requested?.queryParameters['q'], '77641543');
    },
  );

  test('a blank query leaves the products request unfiltered', () async {
    Uri? requested;
    final api = _api((request) async {
      requested = request.url;
      return _json(_productPage([]));
    });

    await api.listProducts('store-id', query: '   ');

    expect(requested?.queryParameters.containsKey('q'), isFalse);
  });

  test(
    'cross-store search reads matches from the elsewhere endpoint',
    () async {
      Uri? requested;
      final api = _api((request) async {
        requested = request.url;
        return _json(_elsewhere());
      });

      final search = await api.searchOtherStores('store-id', '77641543');

      expect(requested?.path, '/api/v1/stores/store-id/products/elsewhere');
      expect(search.normalizedQuery, '77641543');
      expect(search.matches.single.storeName, 'Parts Avto');
      expect(search.matches.single.matchedOn, 'sku');
      expect(search.matches.single.isConnectedStore, isTrue);
    },
  );

  test(
    'an empty local result pulls suggestions from the other stores',
    () async {
      final container = _container(_searchClient());
      addTearDown(container.dispose);
      final provider = storeProductsProvider('store-id');
      await container.read(provider.future);

      await container.read(provider.notifier).applyQuery('77641543');

      final state = container.read(provider).requireValue;
      expect(state.page.items, isEmpty);
      expect(state.isSearchingElsewhere, isFalse);
      expect(state.elsewhere?.matches.single.name, 'Амортизатор капота Passat');
    },
  );

  test('a local hit never asks the other stores', () async {
    var elsewhereRequests = 0;
    final container = _container(
      MockClient((request) async {
        if (request.url.path.endsWith('/products/elsewhere')) {
          elsewhereRequests += 1;
          return _json(_elsewhere());
        }
        if (request.url.path.endsWith('/products')) {
          return _json(_productPage([_product()]));
        }
        return _json(_store());
      }),
    );
    addTearDown(container.dispose);
    final provider = storeProductsProvider('store-id');
    await container.read(provider.future);

    await container.read(provider.notifier).applyQuery('Бендикс');

    expect(elsewhereRequests, 0);
    expect(container.read(provider).requireValue.elsewhere, isNull);
  });

  test('clearing the query drops the cross-store suggestions', () async {
    final container = _container(_searchClient());
    addTearDown(container.dispose);
    final provider = storeProductsProvider('store-id');
    await container.read(provider.future);

    await container.read(provider.notifier).applyQuery('77641543');
    expect(container.read(provider).requireValue.elsewhere, isNotNull);

    await container.read(provider.notifier).applyQuery('');

    final state = container.read(provider).requireValue;
    expect(state.elsewhere, isNull);
    expect(state.hasQuery, isFalse);
    expect(state.page.items, hasLength(1));
  });

  testWidgets('the catalog heading carries the search field', (tester) async {
    await _pumpCatalog(tester, _searchClient());

    expect(find.text('Каталог'), findsOneWidget);
    expect(find.byType(TextField), findsOneWidget);
    expect(
      find.widgetWithText(TextField, 'Поиск по названию, SKU или OEM'),
      findsOneWidget,
    );
    expect(find.text('Найдено в других магазинах'), findsNothing);
  });

  testWidgets('a query with no local hit offers the other store', (
    tester,
  ) async {
    await _pumpCatalog(tester, _searchClient());

    await tester.enterText(find.byType(TextField), '77641543');
    await tester.pumpAndSettle();

    expect(
      find.textContaining('В этом магазине ничего не найдено'),
      findsOneWidget,
    );
    expect(find.text('Найдено в других магазинах'), findsOneWidget);
    expect(find.text('Parts Avto'), findsOneWidget);
    expect(find.text('SKU'), findsOneWidget);
    expect(find.textContaining('по SKU 77641543'), findsOneWidget);
    expect(find.text('Перейти'), findsOneWidget);
  });
}

Future<void> _pumpCatalog(WidgetTester tester, http.Client client) async {
  tester.view.physicalSize = const Size(1280, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        storesApiProvider.overrideWithValue(
          StoresApi(ApiClient(client: client, baseUrl: 'http://api.test')),
        ),
        storeProductsProvider('store-id').overrideWith(
          () => StoreProductsController(
            'store-id',
            searchDebounce: Duration.zero,
          ),
        ),
      ],
      child: MaterialApp(
        theme: AppTheme.light,
        home: const StoreProductsPage(storeId: 'store-id'),
      ),
    ),
  );
  await tester.pumpAndSettle();
}

ProviderContainer _container(http.Client client) {
  return ProviderContainer(
    overrides: [
      storesApiProvider.overrideWithValue(
        StoresApi(ApiClient(client: client, baseUrl: 'http://api.test')),
      ),
      storeProductsProvider('store-id').overrideWith(
        () =>
            StoreProductsController('store-id', searchDebounce: Duration.zero),
      ),
    ],
  );
}

http.Response _json(Object payload) {
  return http.Response(
    jsonEncode(payload),
    200,
    headers: {'content-type': 'application/json; charset=utf-8'},
  );
}

StoresApi _api(Future<http.Response> Function(http.Request) handler) {
  return StoresApi(
    ApiClient(client: MockClient(handler), baseUrl: 'http://api.test'),
  );
}

/// Catalog holding one product that only an empty query returns.
MockClient _searchClient() {
  return MockClient((request) async {
    final path = request.url.path;
    if (path.endsWith('/products/elsewhere')) {
      return _json(_elsewhere());
    }
    if (path.endsWith('/products')) {
      final query = request.url.queryParameters['q'];
      return _json(_productPage(query == null ? [_product()] : []));
    }
    return _json(_store());
  });
}

Map<String, dynamic> _store() => {
  'id': 'store-id',
  'marketplace': 'prom',
  'external_id': '4015921',
  'name': 'АвтоБуст',
  'url': 'https://prom.ua/ua/c4015921-avtobust.html',
  'kind': 'owned',
  'product_count': 1353,
  'last_synced_at': null,
};

Map<String, dynamic> _product() => {
  'id': 'listing-id',
  'name': 'Бендикс MB126',
  'url': 'https://prom.ua/ua/p1-bendiks.html',
  'sku': '1006209539',
  'brand': 'KEMP',
  'current_price': '317.80',
  'currency': 'UAH',
  'is_available': true,
  'image_url': null,
};

Map<String, dynamic> _productPage(List<Map<String, dynamic>> items) => {
  'items': items,
  'total': items.length,
  'limit': 100,
  'offset': 0,
};

Map<String, dynamic> _elsewhere() => {
  'query': '77641543',
  'normalized_query': '77641543',
  'identities': ['77641543'],
  'matches': [
    {
      'source': 'store',
      'store_id': 'parts-avto-store',
      'store_name': 'Parts Avto',
      'marketplace': 'prom',
      'product_id': 'other-listing',
      'name': 'Амортизатор капота Passat',
      'url': 'https://prom.ua/ua/p2858586065-amortizator.html',
      'sku': '77641543',
      'brand': 'KEMP',
      'price': '256.50',
      'currency': 'UAH',
      'image_url': null,
      'matched_on': 'sku',
      'matched_value': '77641543',
      'via_cross': false,
    },
  ],
};
