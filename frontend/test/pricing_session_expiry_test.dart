import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/core/firebase_auth_client.dart';
import 'package:marko_client/features/pricing/pricing_api.dart';
import 'package:marko_client/features/pricing/pricing_controller.dart';
import 'package:marko_client/features/pricing/recommendations_page.dart';

/// A session does not only die between the sign-in screen and the first page.
/// It dies far more often while the operator is already working — on a manual
/// refresh, or on the "показать ещё" that fetches page two — and those paths
/// used to turn a 401 into `error.toString()`: the backend's English
/// "Authentication required" printed as a red inline strip, with no way to sign
/// in again. Auth expiry is one condition and has to be answered in one place,
/// whichever request happened to hit it.
void main() {
  testWidgets('a session that dies before a refresh offers a sign-in', (
    tester,
  ) async {
    final backend = _ExpiringBackend();
    final auth = _RecordingAuthClient();
    await tester.pumpWidget(_app(backend: backend, auth: auth));
    await tester.pumpAndSettle();

    expect(find.text('Product rec-1'), findsOneWidget);

    backend.sessionExpired = true;
    await tester.tap(find.byTooltip('Обновить'));
    await _flush(tester);

    expect(
      find.textContaining('Authentication required'),
      findsNothing,
      reason: 'a backend English string is not an answer for a shop owner',
    );
    expect(find.textContaining('Сессия истекла'), findsOneWidget);
    expect(
      find.text('Product rec-1'),
      findsOneWidget,
      reason:
          'the rows already read are still true; a dead session must not '
          'throw the page away',
    );

    await tester.tap(find.byKey(const ValueKey('marko-reauthenticate')));
    await _flush(tester);

    expect(
      auth.logouts,
      1,
      reason:
          'dropping the dead session is what re-opens the sign-in screen; '
          'without it the operator is stuck',
    );
  });

  testWidgets('a session that dies before page two offers a sign-in', (
    tester,
  ) async {
    final backend = _ExpiringBackend();
    final auth = _RecordingAuthClient();
    await tester.pumpWidget(_app(backend: backend, auth: auth));
    await tester.pumpAndSettle();

    final loadMore = find.textContaining('Показать ещё');
    expect(loadMore, findsOneWidget);
    await tester.ensureVisible(loadMore);
    await tester.pumpAndSettle();

    backend.sessionExpired = true;
    await tester.tap(loadMore);
    // Bounded pumps: the "показать ещё" button swaps its icon for a spinner,
    // and `pumpAndSettle` would spin against that animation until the test
    // timeout instead of observing the state under test.
    await _flush(tester);

    expect(find.textContaining('Authentication required'), findsNothing);
    expect(find.textContaining('Сессия истекла'), findsOneWidget);

    final reauthenticate = find.byKey(const ValueKey('marko-reauthenticate'));
    await tester.ensureVisible(reauthenticate);
    await tester.pumpAndSettle();
    await tester.tap(reauthenticate);
    await _flush(tester);

    expect(auth.logouts, 1);
  });

  test('every controller failure path classifies an expired session', () async {
    final backend = _ExpiringBackend();
    final container = ProviderContainer(
      overrides: [
        pricingApiProvider.overrideWithValue(
          PricingApi(
            ApiClient(client: backend.client, baseUrl: 'http://api.test'),
          ),
        ),
      ],
    );
    addTearDown(container.dispose);

    await container.read(recommendationsControllerProvider.future);
    backend.sessionExpired = true;

    await container.read(recommendationsControllerProvider.notifier).refresh();
    expect(
      container.read(recommendationsControllerProvider).requireValue.error,
      isNull,
      reason: 'an expired session is not a message to print and forget',
    );
    expect(
      container
          .read(recommendationsControllerProvider)
          .requireValue
          .sessionExpired,
      isTrue,
    );

    await container.read(recommendationsControllerProvider.notifier).loadMore();
    expect(
      container
          .read(recommendationsControllerProvider)
          .requireValue
          .sessionExpired,
      isTrue,
      reason: 'pagination hits the same dead token as the refresh does',
    );
    expect(
      container
          .read(recommendationsControllerProvider)
          .requireValue
          .isLoadingMore,
      isFalse,
    );

    await container
        .read(recommendationsControllerProvider.notifier)
        .showLatestRun();
    expect(
      container
          .read(recommendationsControllerProvider)
          .requireValue
          .sessionExpired,
      isTrue,
    );
  });
}

/// Lets the queued HTTP futures resolve without settling.
Future<void> _flush(WidgetTester tester) async {
  await tester.pump();
  for (var i = 0; i < 6; i += 1) {
    await tester.pump(const Duration(milliseconds: 20));
  }
}

Widget _app({
  required _ExpiringBackend backend,
  required _RecordingAuthClient auth,
}) {
  return ProviderScope(
    retry: (_, _) => null,
    overrides: [
      apiClientProvider.overrideWithValue(
        ApiClient(client: backend.client, baseUrl: 'http://api.test'),
      ),
      authClientProvider.overrideWithValue(auth),
    ],
    child: MaterialApp(
      theme: AppTheme.light,
      locale: const Locale('ru'),
      supportedLocales: const [Locale('ru'), Locale('uk')],
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
      home: const Scaffold(body: RecommendationsPage()),
    ),
  );
}

/// Serves one healthy page and then answers every request the way an expired
/// session does.
class _ExpiringBackend {
  bool sessionExpired = false;

  http.Client get client => MockClient((request) async {
    if (sessionExpired) {
      return http.Response(
        jsonEncode({'detail': 'Authentication required'}),
        401,
        headers: {'content-type': 'application/json'},
      );
    }
    final path = request.url.path;
    if (path == '/api/v1/pricing/recommendations') {
      return _jsonResponse({
        'items': [_recommendationJson('rec-1'), _recommendationJson('rec-2')],
        'total': 3,
        'run_id': 'run-1',
        'limit': 2,
        'offset': int.parse(request.url.queryParameters['offset'] ?? '0'),
        'action_counts': {
          'raise': 3,
          'lower': 0,
          'review': 0,
          'hold': 0,
          'total': 3,
        },
      });
    }
    if (path == '/api/v1/pricing/runs') {
      return _jsonResponse({
        'items': <Object>[],
        'total': 0,
        'limit': 25,
        'offset': 0,
      });
    }
    if (path == '/api/v1/catalog/imports') {
      return _jsonResponse({
        'items': <Object>[],
        'total': 0,
        'limit': 100,
        'offset': 0,
      });
    }
    return http.Response('not found', 404);
  });
}

http.Response _jsonResponse(Object payload) => http.Response(
  jsonEncode(payload),
  200,
  headers: {'content-type': 'application/json'},
);

Map<String, dynamic> _recommendationJson(String id) => {
  'id': id,
  'pricing_run_id': 'run-1',
  'catalog_snapshot_id': 'snapshot-1',
  'catalog_item_id': 'item-$id',
  'sku': 'SKU-$id',
  'oe_norm': 'OE-$id',
  'name': 'Product $id',
  'category': 'brakes',
  'stock_status': 'fresh',
  'action': 'RAISE',
  'current_price': '100',
  'recommended_price': '110',
  'confidence': '0.8',
  'confidence_grade': 'A',
  'competitor_count': 3,
  'priority_score': '10',
  'priority_score_type': 'gross_uplift_opportunity',
  'reason_codes': <String>[],
  'currency': 'UAH',
  'price_tick': '1',
  'computed_at': '2026-07-30T00:00:00Z',
};

class _RecordingAuthClient implements AuthClient {
  int logouts = 0;

  @override
  AuthSession? get currentSession => null;

  @override
  Stream<AuthSession?> get authStateChanges => const Stream.empty();

  @override
  Future<AuthSession> login(String email, String password) async =>
      throw UnimplementedError();

  @override
  Future<void> register(String email, String password) async =>
      throw UnimplementedError();

  @override
  Future<AuthSession> loginWithGoogle() async => throw UnimplementedError();

  @override
  Future<void> logout() async => logouts += 1;

  @override
  Future<String?> idToken({bool forceRefresh = false}) async => null;
}
