import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/features/stores/stores_api.dart';
import 'package:marko_client/features/stores/stores_controller.dart';

void main() {
  test('accepts canonical Prom seller URL', () {
    expect(
      isSupportedPromStoreUrl('https://prom.ua/ua/c2847093-kemp.html'),
      isTrue,
    );
  });

  test('accepts public Prom seller subdomain', () {
    expect(isSupportedPromStoreUrl('https://pilot-avto.prom.ua/ua/'), isTrue);
  });

  test('rejects non-HTTPS and lookalike hosts', () {
    expect(isSupportedPromStoreUrl('http://pilot-avto.prom.ua/ua/'), isFalse);
    expect(
      isSupportedPromStoreUrl('https://prom.ua.evil.example/store'),
      isFalse,
    );
  });

  test('deletes a store from state after the backend confirms it', () async {
    final api = StoresApi(
      ApiClient(
        client: MockClient((request) async {
          if (request.method == 'GET') {
            return http.Response(jsonEncode([_storeJson()]), 200);
          }
          expect(request.method, 'DELETE');
          expect(request.url.path, '/api/v1/stores/store-id');
          return http.Response('', 204);
        }),
        baseUrl: 'http://api.test',
      ),
    );
    final container = ProviderContainer(
      overrides: [storesApiProvider.overrideWithValue(api)],
    );
    addTearDown(container.dispose);

    final initial = await container.read(storesControllerProvider.future);
    final deleted = await container
        .read(storesControllerProvider.notifier)
        .deleteStore(initial.stores.single);

    expect(deleted, isTrue);
    expect(
      container.read(storesControllerProvider).requireValue.stores,
      isEmpty,
    );
    expect(
      container.read(storesControllerProvider).requireValue.deletingStoreId,
      isNull,
    );
  });
}

Map<String, dynamic> _storeJson() => {
  'id': 'store-id',
  'marketplace': 'prom',
  'external_id': '2847093',
  'name': 'Kemp',
  'url': 'https://prom.ua/ua/c2847093-kemp.html',
  'kind': 'owned',
  'product_count': 12,
  'last_synced_at': '2026-07-13T12:00:00Z',
};
