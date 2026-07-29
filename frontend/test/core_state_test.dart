import 'dart:async';
import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/core/app_language.dart';
import 'package:marko_client/core/system_status.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('restores and persists the selected application language', () async {
    SharedPreferences.setMockInitialValues({
      'marko.app_language': AppLanguage.ukrainian.name,
    });
    final container = ProviderContainer();
    addTearDown(container.dispose);

    expect(container.read(appLanguageProvider), AppLanguage.russian);
    await _waitUntil(
      () => container.read(appLanguageProvider) == AppLanguage.ukrainian,
    );

    container.read(appLanguageProvider.notifier).select(AppLanguage.russian);
    await _waitUntil(() async {
      final preferences = await SharedPreferences.getInstance();
      return preferences.getString('marko.app_language') ==
          AppLanguage.russian.name;
    });
  });

  test(
    'reports collection-limited only when backend readiness is healthy',
    () async {
      final requestedPaths = <String>[];
      final client = ApiClient(
        client: MockClient((request) async {
          requestedPaths.add(request.url.path);
          if (request.url.path == '/api/v1/health/ready') {
            return http.Response(jsonEncode({'status': 'ok'}), 200);
          }
          if (request.url.path == '/api/v1/health/source-access') {
            return http.Response(
              jsonEncode({'live_collection_allowed': false}),
              200,
            );
          }
          return http.Response('not found', 404);
        }),
        baseUrl: 'http://api.test',
      );
      final container = ProviderContainer(
        overrides: [apiClientProvider.overrideWithValue(client)],
      );
      addTearDown(container.dispose);

      final status = await container.read(systemStatusProvider.future);

      expect(status, SystemHealth.collectionLimited);
      expect(
        requestedPaths,
        containsAll(['/api/v1/health/ready', '/api/v1/health/source-access']),
      );
    },
  );

  test('surfaces an unavailable backend as a provider error', () async {
    final client = ApiClient(
      client: MockClient((request) async {
        if (request.url.path == '/api/v1/health/ready') {
          return http.Response(
            jsonEncode({'detail': 'Database is unavailable'}),
            503,
          );
        }
        return http.Response(
          jsonEncode({'live_collection_allowed': false}),
          200,
        );
      }),
      baseUrl: 'http://api.test',
    );
    final container = ProviderContainer(
      overrides: [apiClientProvider.overrideWithValue(client)],
    );
    addTearDown(container.dispose);
    final emittedError = Completer<Object>();
    final subscription = container.listen(systemStatusProvider, (_, next) {
      final error = next.error;
      if (error != null && !emittedError.isCompleted) {
        emittedError.complete(error);
      }
    }, fireImmediately: true);
    addTearDown(subscription.close);

    await expectLater(
      emittedError.future,
      completion(
        isA<ApiException>().having(
          (error) => error.statusCode,
          'statusCode',
          503,
        ),
      ),
    );
  });
}

Future<void> _waitUntil(
  FutureOr<bool> Function() condition, {
  int attempts = 50,
}) async {
  for (var attempt = 0; attempt < attempts; attempt++) {
    if (await condition()) return;
    await Future<void>.delayed(Duration.zero);
  }
  fail('Condition was not met after $attempts event-loop turns');
}
