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
import 'package:marko_client/core/session_expiry.dart';
import 'package:marko_client/features/pricing/pricing_api.dart';
import 'package:marko_client/features/pricing/pricing_controller.dart';
import 'package:marko_client/features/pricing/pricing_run_panel.dart';
import 'package:marko_client/features/pricing/recommendations_page.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// The token dies once; which request happens to meet it is an accident of
/// timing. So the answer must not depend on it.
///
/// It did. A refresh printed the backend's English "Authentication required".
/// A permanent link reported that the recommendation "no longer exists or is
/// not in this workspace" — a claim about the operator's data that was never
/// true. An export dropped a snackbar with the exception text and let it scroll
/// away. Starting a calculation offered the same button again, which could only
/// fail again. Each of these is a different wrong answer to one condition that
/// has exactly one resolution.
///
/// Every path below therefore has to arrive at the same place: no backend
/// string, no retry, and the sign-in that actually fixes it.
void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('paths that keep the page and answer in place', () {
    testWidgets('the run preview', (tester) async {
      final harness = await _open(tester, expire: {'preview'});
      await tester.tap(find.byKey(const ValueKey('pricing-run-start')));
      await _flush(tester);

      expect(
        tester
            .widget<FilledButton>(
              find.byKey(const ValueKey('pricing-run-start')),
            )
            .onPressed,
        isNull,
        reason: 'confirming a calculation on a dead token cannot start one',
      );
      await _expectAnsweredOnce(tester, harness);
    });

    testWidgets('the run start', (tester) async {
      final harness = await _open(tester, expire: {'start'});
      await tester.tap(find.byKey(const ValueKey('pricing-run-start')));
      await _flush(tester);
      expect(find.text('Запустить расчёт цен?'), findsOneWidget);
      await tester.tap(find.text('Запустить').last);
      await _flush(tester);

      await _expectAnsweredOnce(tester, harness);
    });

    testWidgets('the status poll', (tester) async {
      // A run started before the reload is still working, and the panel resumes
      // watching it on its own — nobody pressed anything.
      final harness = await _open(
        tester,
        expire: {'poll'},
        activeRunStatus: 'running',
      );

      await _expectAnsweredOnce(tester, harness);
      expect(
        find.textContaining('Расчёт завершился с ошибкой'),
        findsNothing,
        reason: 'a status read that failed is not a run that failed',
      );
    });

    testWidgets('the cancellation', (tester) async {
      final harness = await _open(
        tester,
        expire: {'cancel'},
        activeRunStatus: 'running',
      );
      await tester.tap(find.byKey(const ValueKey('pricing-run-cancel')));
      await _flush(tester);
      expect(find.text('Отменить расчёт?'), findsOneWidget);
      await tester.tap(find.text('Отменить расчёт').last);
      await _flush(tester);

      await _expectAnsweredOnce(tester, harness);
      await _settlePolling(tester, harness);
    });

    testWidgets('the export', (tester) async {
      final harness = await _open(tester, expire: {'export'});
      await tester.tap(find.byKey(const ValueKey('recommendations-export')));
      await _flush(tester);
      await tester.tap(find.text('Excel (.xlsx)'));
      await _flush(tester);

      await _expectAnsweredOnce(tester, harness);
    });

    testWidgets('the manual refresh', (tester) async {
      final harness = await _open(tester, expire: {});
      harness.backend.expire.add('list');
      await tester.tap(find.byTooltip('Обновить'));
      await _flush(tester);

      expect(
        tester
            .widget<IconButton>(
              find.widgetWithIcon(IconButton, Icons.refresh_rounded),
            )
            .onPressed,
        isNull,
        reason: 'the same request with the same dead token can only fail again',
      );
      await _expectAnsweredOnce(tester, harness);
    });

    testWidgets('the next page', (tester) async {
      final harness = await _open(tester, expire: {});
      final loadMore = find.textContaining('Показать ещё');
      await tester.ensureVisible(loadMore);
      await _flush(tester);
      harness.backend.expire.add('list');
      await tester.tap(loadMore);
      await _flush(tester);

      await _expectAnsweredOnce(tester, harness);
    });

    testWidgets('and the offer comes back down once it is taken', (
      tester,
    ) async {
      final harness = await _open(tester, expire: {});
      harness.backend.expire.add('list');
      await tester.tap(find.byTooltip('Обновить'));
      await _flush(tester);
      // `_expectAnsweredOnce` already took the offer, so the dead credential is
      // gone. Leaving the notice up past that point tells an operator who is
      // about to sign in — or already has — that their session is still dead,
      // and keeps the page read-only for no reason.
      await _expectAnsweredOnce(tester, harness);
      harness.backend.expire.remove('list');
      await _flush(tester);

      expect(find.textContaining('Сессия истекла'), findsNothing);
      expect(
        tester
            .widget<IconButton>(
              find.widgetWithIcon(IconButton, Icons.refresh_rounded),
            )
            .onPressed,
        isNotNull,
      );
    });

    testWidgets('the deep link', (tester) async {
      final harness = await _open(
        tester,
        expire: {'recommendation'},
        deepLinkId: 'rec-elsewhere',
      );

      await _expectAnsweredOnce(tester, harness);
      expect(
        find.textContaining('больше не существует'),
        findsNothing,
        reason:
            'the row exists; saying otherwise is a false statement about the '
            'operator’s catalogue and hides the one action that opens it',
      );
    });
  });

  testWidgets('a run panel with no page above it answers for itself', (
    tester,
  ) async {
    // The page owns the single answer only because it is there. Suppressing
    // the panel's own copy must not turn into swallowing the 401 outright.
    final backend = _PathBackend()..expire.add('runs');
    final auth = _RecordingAuthClient();
    await tester.pumpWidget(
      ProviderScope(
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
          home: Scaffold(
            body: PricingRunPanel(
              canAdministerWorkspace: true,
              onRunFinished: () {},
            ),
          ),
        ),
      ),
    );
    await _flush(tester, rounds: 12);

    expect(find.textContaining('Authentication required'), findsNothing);
    expect(
      find.byKey(const ValueKey('pricing-run-session-expired')),
      findsOneWidget,
    );
    await tester.tap(find.byKey(const ValueKey('marko-reauthenticate')));
    await _flush(tester);
    expect(auth.logouts, 1);
  });

  group('the controller funnel', () {
    test('a deep link keeps the link alive and asks for a sign-in', () async {
      final backend = _PathBackend();
      final container = _container(backend);
      await container.read(recommendationsControllerProvider.future);

      backend.expire.add('recommendation');
      await container
          .read(recommendationsControllerProvider.notifier)
          .ensureVisible('rec-elsewhere');

      final state = container
          .read(recommendationsControllerProvider)
          .requireValue;
      expect(state.sessionExpired, isTrue);
      expect(
        state.deepLinkUnavailable,
        isFalse,
        reason: 'a dead session is not a missing recommendation',
      );
      expect(state.error, isNull);
      expect(container.read(markoSessionExpiredProvider), isTrue);
    });

    test('saving catalog context', () async {
      final backend = _PathBackend();
      final container = _container(backend);
      await container.read(recommendationsControllerProvider.future);

      backend.expire.add('override');
      final saved = await container
          .read(recommendationsControllerProvider.notifier)
          .saveCatalogContext('item-1', {'stock_status': 'fresh'});

      expect(saved, isFalse);
      final state = container
          .read(recommendationsControllerProvider)
          .requireValue;
      expect(state.sessionExpired, isTrue);
      expect(state.error, isNull);
      expect(container.read(markoSessionExpiredProvider), isTrue);
    });

    test('recording a decision', () async {
      final backend = _PathBackend();
      final container = _container(backend);
      await container.read(recommendationsControllerProvider.future);

      backend.expire.add('decision');
      final recorded = await container
          .read(recommendationsControllerProvider.notifier)
          .recordDecision('rec-1', {'decision': 'accepted'});

      expect(recorded, isFalse);
      final state = container
          .read(recommendationsControllerProvider)
          .requireValue;
      expect(state.sessionExpired, isTrue);
      expect(state.error, isNull);
      expect(container.read(markoSessionExpiredProvider), isTrue);
    });

    test('a live response takes the offer back down', () async {
      final backend = _PathBackend();
      final container = _container(backend);
      await container.read(recommendationsControllerProvider.future);

      backend.expire.add('list');
      await container
          .read(recommendationsControllerProvider.notifier)
          .refresh();
      expect(container.read(markoSessionExpiredProvider), isTrue);

      backend.expire.remove('list');
      await container
          .read(recommendationsControllerProvider.notifier)
          .refresh();
      expect(
        container.read(markoSessionExpiredProvider),
        isFalse,
        reason:
            'a signed-in operator must not keep reading that their session '
            'expired',
      );
    });

    test('a 500 is still a 500 and still says so', () async {
      final backend = _PathBackend();
      final container = _container(backend);
      await container.read(recommendationsControllerProvider.future);

      backend.brokenPaths.add('list');
      await container
          .read(recommendationsControllerProvider.notifier)
          .refresh();

      final state = container
          .read(recommendationsControllerProvider)
          .requireValue;
      expect(state.sessionExpired, isFalse);
      expect(state.error, isNotNull);
      expect(
        container.read(markoSessionExpiredProvider),
        isFalse,
        reason: 'signing in again does not fix a broken backend',
      );
    });
  });
}

/// The one answer, and only one of it.
Future<void> _expectAnsweredOnce(WidgetTester tester, _Harness harness) async {
  expect(
    find.textContaining('Authentication required'),
    findsNothing,
    reason: 'a backend English string is not an answer for a shop owner',
  );
  expect(
    find.textContaining('Сессия истекла'),
    findsOneWidget,
    reason:
        'two copies of the same sentence read as two different problems, and '
        'none reads as none',
  );
  expect(find.text('Повторить'), findsNothing);

  final reauthenticate = find.byKey(const ValueKey('marko-reauthenticate'));
  expect(reauthenticate, findsOneWidget);
  await tester.ensureVisible(reauthenticate);
  await _flush(tester);
  await tester.tap(reauthenticate);
  await _flush(tester);
  expect(
    harness.auth.logouts,
    1,
    reason:
        'dropping the dead credential is what re-opens the sign-in screen; '
        'without it the operator is stuck looking at the offer',
  );
  expect(tester.takeException(), isNull);
}

class _Harness {
  _Harness(this.backend, this.auth);

  final _PathBackend backend;
  final _RecordingAuthClient auth;
}

/// A run that never finishes leaves the panel's backoff timer armed, and the
/// binding refuses to tear a tree down under one. Let the run reach a terminal
/// status instead of silencing the check.
Future<void> _settlePolling(WidgetTester tester, _Harness harness) async {
  harness.backend.pollStatus = 'completed';
  for (var i = 0; i < 6; i += 1) {
    await tester.pump(const Duration(seconds: 20));
    await _flush(tester);
  }
}

Future<_Harness> _open(
  WidgetTester tester, {
  required Set<String> expire,
  String? activeRunStatus,
  String? deepLinkId,
}) async {
  tester.view.physicalSize = const Size(1500, 3000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final backend = _PathBackend(activeRunStatus: activeRunStatus)
    ..expire.addAll(expire);
  final auth = _RecordingAuthClient();
  await tester.pumpWidget(
    ProviderScope(
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
        home: Scaffold(
          body: RecommendationsPage(
            canAdministerWorkspace: true,
            initialRecommendationId: deepLinkId,
          ),
        ),
      ),
    ),
  );
  // Bounded pumps everywhere: a live run animates a progress bar and the start
  // button swaps its icon for a spinner, so `pumpAndSettle` would race the
  // animation until the test times out instead of observing the state.
  await _flush(tester, rounds: 16);
  return _Harness(backend, auth);
}

Future<void> _flush(WidgetTester tester, {int rounds = 8}) async {
  await tester.pump();
  for (var i = 0; i < rounds; i += 1) {
    await tester.pump(const Duration(milliseconds: 20));
  }
}

ProviderContainer _container(_PathBackend backend) {
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
  return container;
}

/// A backend whose session dies on exactly the named request, so each path can
/// be met on its own instead of behind whichever one fires first.
class _PathBackend {
  _PathBackend({this.activeRunStatus}) : pollStatus = activeRunStatus;

  final String? activeRunStatus;
  String? pollStatus;
  final Set<String> expire = {};
  final Set<String> brokenPaths = {};

  http.Client get client => MockClient((request) async {
    final path = request.url.path;
    final method = request.method;
    final name = switch (path) {
      '/api/v1/pricing/recommendations' => 'list',
      '/api/v1/pricing/recommendations/export' => 'export',
      '/api/v1/pricing/runs' => method == 'POST' ? 'start' : 'runs',
      '/api/v1/pricing/runs/preview' => 'preview',
      '/api/v1/pricing/runs/run-1' => 'poll',
      '/api/v1/pricing/runs/run-1/cancel' => 'cancel',
      '/api/v1/catalog/imports' => 'imports',
      _ when path.endsWith('/overrides') => 'override',
      _ when path.endsWith('/decisions') => 'decision',
      _ when path.startsWith('/api/v1/pricing/recommendations/') =>
        'recommendation',
      _ => 'other',
    };
    if (expire.contains(name)) {
      return http.Response(
        jsonEncode({'detail': 'Authentication required'}),
        401,
        headers: {'content-type': 'application/json'},
      );
    }
    if (brokenPaths.contains(name)) {
      return http.Response(
        jsonEncode({'detail': 'Pricing service is unavailable'}),
        500,
        headers: {'content-type': 'application/json'},
      );
    }
    switch (name) {
      case 'list':
        return _json({
          'items': [_recommendation('rec-1'), _recommendation('rec-2')],
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
      case 'recommendation':
        return _json(_recommendation('rec-elsewhere'));
      case 'runs':
        final active = activeRunStatus;
        return _json({
          'items': active == null ? <Object>[] : [_run(active)],
          'total': active == null ? 0 : 1,
          'limit': 25,
          'offset': 0,
        });
      case 'poll':
        return _json(_run(pollStatus ?? 'completed'));
      case 'cancel':
        return _json(_run('cancelled'));
      case 'preview':
        return _json(_preview());
      case 'start':
        return _json(_run('completed'), statusCode: 202);
      case 'imports':
        return _json({
          'items': [
            {
              'id': 'batch-1',
              'filename': 'catalog.xlsx',
              'status': 'completed',
              'column_mapping': {'sku': 'SKU'},
              'total_rows': 10,
              'imported_rows': 10,
              'rejected_rows': 0,
              'error_log': <Object>[],
              'created_at': '2026-07-30T04:00:00Z',
            },
          ],
          'total': 1,
          'limit': 100,
          'offset': 0,
        });
      case 'override':
      case 'decision':
        return _json(<String, dynamic>{});
      default:
        return http.Response('not found', 404);
    }
  });
}

http.Response _json(Object payload, {int statusCode = 200}) => http.Response(
  jsonEncode(payload),
  statusCode,
  headers: {'content-type': 'application/json'},
);

Map<String, dynamic> _run(String status) => {
  'id': 'run-1',
  'import_batch_id': 'batch-1',
  'status': status,
  'coefficient_model': 'shrinkage',
  'coefficient_version': null,
  'calibration_dataset_hash': null,
  'calibration_accounting': <String, dynamic>{},
  'total_items': 10,
  'completed_items': 4,
  'failed_items': 0,
  'manual_review_items': 0,
  'cancel_requested': false,
  'error': null,
  'created_at': '2026-07-30T04:00:00Z',
};

Map<String, dynamic> _preview() => {
  'scope_contract_version': 'v1',
  'import_batch_id': 'batch-1',
  'scope_mode': 'FULL_CATALOG',
  'policy_version': 'test-v1',
  'catalog_snapshot_hash': 'a' * 64,
  'scope_hash': 'b' * 64,
  'preview_token': 'mrp1_testtoken0000000000000000000000000000',
  'requires_full_catalog_confirmation': true,
  'estimate': {
    'requested_items': 10,
    'eligible_items': 10,
    'excluded_items': 0,
    'unique_scrape_inputs': 10,
    'duplicate_items': 0,
    'worst_case_duration_seconds': 120,
  },
  'exclusions': <Map<String, dynamic>>[],
  'exclusions_truncated': false,
  'scope_manifest': <String, dynamic>{},
};

Map<String, dynamic> _recommendation(String id) => {
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
