import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/features/stores/stores_api.dart';

void main() {
  test('loads stores from the FastAPI REST endpoint', () async {
    final service = StoresApi(
      ApiClient(
        client: MockClient((request) async {
          expect(request.method, 'GET');
          expect(request.url.path, '/api/v1/stores');
          return http.Response(
            jsonEncode([
              {
                'id': 'store-id',
                'marketplace': 'prom',
                'external_id': '2847093',
                'name': 'Kemp',
                'url': 'https://prom.ua/ua/c2847093-kemp.html',
                'kind': 'owned',
                'product_count': 12,
                'last_synced_at': '2026-07-13T12:00:00Z',
              },
            ]),
            200,
          );
        }),
        baseUrl: 'http://api.test',
      ),
    );

    final stores = await service.listStores();

    expect(stores, hasLength(1));
    expect(stores.single.displayName, 'Kemp');
    expect(stores.single.productCount, 12);
  });

  test('sends store registration to the custom backend', () async {
    final service = StoresApi(
      ApiClient(
        client: MockClient((request) async {
          expect(request.method, 'POST');
          expect(request.url.path, '/api/v1/stores');
          expect(jsonDecode(request.body), {
            'url': 'https://prom.ua/ua/c2847093-kemp.html',
          });
          return http.Response(
            jsonEncode({
              'store_id': 'store-id',
              'sync_run_id': 'sync-id',
              'status': 'queued',
            }),
            202,
          );
        }),
        baseUrl: 'http://api.test',
      ),
    );

    final sync = await service.addStore(
      'https://prom.ua/ua/c2847093-kemp.html',
    );

    expect(sync.storeId, 'store-id');
    expect(sync.syncRunId, 'sync-id');
    expect(sync.status, 'queued');
  });

  test('preserves FastAPI error details', () async {
    final client = ApiClient(
      client: MockClient((request) async {
        return http.Response(jsonEncode({'detail': 'Store not found'}), 404);
      }),
      baseUrl: 'http://api.test',
    );

    expect(
      () => client.getJson('/api/v1/stores/missing'),
      throwsA(
        isA<ApiException>()
            .having((error) => error.statusCode, 'statusCode', 404)
            .having((error) => error.message, 'message', 'Store not found'),
      ),
    );
  });
}
