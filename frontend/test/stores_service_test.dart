import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/features/products/products_api.dart';

void main() {
  test('sends store registration to the backend', () async {
    final service = ProductsApi(
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

  test('fetches sync job details', () async {
    final service = ProductsApi(
      ApiClient(
        client: MockClient((request) async {
          expect(request.method, 'GET');
          expect(request.url.path, '/api/v1/jobs/sync-123');
          return http.Response(
            jsonEncode({
              'status': 'completed',
              'progress_current': 100,
              'progress_total': 100,
              'error': null,
            }),
            200,
          );
        }),
        baseUrl: 'http://api.test',
      ),
    );

    final job = await service.getJob('sync-123');
    expect(job.status, 'completed');
    expect(job.isFinished, isTrue);
    expect(job.progress, 1.0);
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
