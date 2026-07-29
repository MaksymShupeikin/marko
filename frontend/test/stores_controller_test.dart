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

  test('stops job polling after a bounded number of failures', () async {
    var jobRequests = 0;
    var jobAvailable = false;
    final api = StoresApi(
      ApiClient(
        client: MockClient((request) async {
          if (request.method == 'GET' && request.url.path == '/api/v1/stores') {
            return http.Response('[]', 200);
          }
          if (request.method == 'POST' &&
              request.url.path == '/api/v1/stores') {
            return http.Response(
              jsonEncode({
                'store_id': 'store-id',
                'sync_run_id': 'sync-id',
                'status': 'queued',
              }),
              202,
            );
          }
          if (request.method == 'GET' &&
              request.url.path == '/api/v1/jobs/sync-id') {
            jobRequests += 1;
            if (jobAvailable) {
              return http.Response(
                jsonEncode({
                  'status': 'completed',
                  'progress_current': 12,
                  'progress_total': 12,
                  'error': null,
                }),
                200,
              );
            }
            return http.Response('temporarily unavailable', 503);
          }
          return http.Response('not found', 404);
        }),
        baseUrl: 'http://api.test',
      ),
    );
    final container = ProviderContainer(
      overrides: [
        storesApiProvider.overrideWithValue(api),
        storesControllerProvider.overrideWith(
          () => StoresController(
            pollBaseDelay: Duration.zero,
            maxConsecutivePollFailures: 3,
          ),
        ),
      ],
    );
    addTearDown(container.dispose);
    await container.read(storesControllerProvider.future);

    final accepted = await container
        .read(storesControllerProvider.notifier)
        .addStore('https://prom.ua/ua/c2847093-kemp.html');
    expect(accepted, isTrue);
    await _waitForMonitoringFailure(container);

    final state = container.read(storesControllerProvider).requireValue;
    expect(jobRequests, 3);
    expect(state.activeJob?.status, 'monitoring_failed');
    expect(state.activeJob?.isFinished, isTrue);
    expect(state.error, contains('нескольких попыток'));

    jobAvailable = true;
    container.read(storesControllerProvider.notifier).retryMonitoring();
    await _waitForJobStatus(container, 'completed');

    expect(jobRequests, 4);
    expect(container.read(storesControllerProvider).requireValue.error, isNull);
  });
}

Future<void> _waitForMonitoringFailure(ProviderContainer container) =>
    _waitForJobStatus(container, 'monitoring_failed');

Future<void> _waitForJobStatus(
  ProviderContainer container,
  String expectedStatus,
) async {
  for (var attempt = 0; attempt < 50; attempt++) {
    final status = container
        .read(storesControllerProvider)
        .value
        ?.activeJob
        ?.status;
    if (status == expectedStatus) return;
    await Future<void>.delayed(Duration.zero);
  }
  fail('Polling did not reach $expectedStatus');
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
