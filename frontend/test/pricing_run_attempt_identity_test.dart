import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/pricing/pricing_run_attempt_store.dart';
import 'package:marko_client/features/pricing/pricing_run_panel.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// The idempotency key answers "is this the same attempt?", and an attempt is
/// not something a widget owns. A shop owner starts a calculation, reloads the
/// tab — because the run is long, because the laptop slept, because they simply
/// pressed F5 — and asks for a fresh one. If the attempt id restarts with the
/// widget, the second confirmation carries the key the first one already spent:
/// the backend answers with the *original*, already finished run, and the
/// operator reads yesterday's prices with no error and nothing to explain them.
///
/// The mirror case is the one that makes a counter tempting: a start whose
/// response was lost may still have created the run, so the retry — including a
/// retry after a reload — must land on the same attempt instead of scraping the
/// whole catalogue twice.
void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('a deliberate rerun after a reload is a new attempt', (
    tester,
  ) async {
    final backend = _RunBackend();
    await tester.pumpWidget(_app(backend));
    await tester.pumpAndSettle();

    await _startAndConfirm(tester);
    expect(backend.startBodies, hasLength(1));

    await _reloadApp(tester, backend);

    // Same import, same catalogue, same scope — a deliberate recalculation
    // after a reload.
    await _startAndConfirm(tester);

    expect(backend.startBodies, hasLength(2));
    expect(
      backend.startBodies.first['idempotency_key'],
      isNot(backend.startBodies.last['idempotency_key']),
      reason:
          'an attempt counter that lives in widget state restarts at 1 after '
          'every reload, so the backend hands back the old terminal run',
    );
    expect(
      backend.startBodies.map((body) => body['expected_scope_hash']).toSet(),
      hasLength(1),
      reason: 'the scope really is identical — only the attempt is new',
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('a start whose response was lost keeps its attempt across a '
      'reload', (tester) async {
    final backend = _RunBackend(failFirstStart: true);
    await tester.pumpWidget(_app(backend));
    await tester.pumpAndSettle();

    await _startAndConfirm(tester);
    expect(backend.startBodies, hasLength(1));
    expect(find.textContaining('temporarily unavailable'), findsOneWidget);

    await _reloadApp(tester, backend);

    // The response was lost, not necessarily the run. This is the same
    // uncertain attempt, and it must not become a second scrape of the whole
    // catalogue just because the tab was reloaded in between.
    await _startAndConfirm(tester);

    expect(backend.startBodies, hasLength(2));
    expect(
      backend.startBodies.first['idempotency_key'],
      backend.startBodies.last['idempotency_key'],
      reason: 'an unfinished attempt has to outlive the widget and the tab',
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('the outstanding attempt is durable, and a closed one is gone', (
    tester,
  ) async {
    final backend = _RunBackend(failFirstStart: true);
    await tester.pumpWidget(_app(backend));
    await tester.pumpAndSettle();

    await _startAndConfirm(tester);
    final pending = (await SharedPreferences.getInstance()).getString(
      PricingRunAttemptStore.preferenceKey,
    );
    expect(
      pending,
      isNotNull,
      reason:
          'a key that only lives in this Dart isolate cannot survive the '
          'reload it exists to survive',
    );
    expect(pending, contains(backend.startBodies.first['idempotency_key']));

    // The retry succeeds: the attempt is closed and must not bind the next one.
    await _startAndConfirm(tester);
    expect(
      (await SharedPreferences.getInstance()).getString(
        PricingRunAttemptStore.preferenceKey,
      ),
      isNull,
      reason:
          'a spent key left in storage would deduplicate every later run of '
          'the same catalogue against a finished one',
    );
  });

  test('a reissued attempt is never the previous one', () async {
    SharedPreferences.setMockInitialValues({});
    final store = PricingRunAttemptStore();
    const identity = 'run:batch-1:FULL_CATALOG:scope-hash:snapshot-hash';

    final keys = <String>{};
    for (var attempt = 0; attempt < 40; attempt += 1) {
      final key = await store.reserve(identity);
      keys.add(key);
      expect(await store.reserve(identity), key, reason: 'still one attempt');
      await store.release(identity);
    }

    expect(keys, hasLength(40));
    expect(
      keys.every((key) => key.length >= 8 && key.length <= 160),
      isTrue,
      reason: 'the backend contract bounds the key at 8..160 characters',
    );
  });

  testWidgets('storage that cannot answer stops the run instead of wedging '
      'the start', (tester) async {
    // Раньше здесь стоял `SharedPreferences.resetStatic()` и обещание, что
    // хранилище после него «не отвечает никогда». Это неправда: `resetStatic`
    // сбрасывает только кэш экземпляра, а установленный в `setUp` мок остаётся
    // на месте — проверка шла по полностью исправному хранилищу и не могла
    // упасть. Отказ хранилища подставляется явно.
    final backend = _RunBackend();
    await tester.pumpWidget(
      _app(backend, attemptStorage: const _UnavailableStorage()),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const ValueKey('pricing-run-start')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Запустить').last);
    await tester.pump();
    // Past the storage budget, not past a fixed number of frames.
    await tester.pump(const Duration(seconds: 5));
    for (var i = 0; i < 8; i += 1) {
      await tester.pump();
    }

    expect(
      backend.startBodies,
      isEmpty,
      reason:
          'an attempt nobody can write down cannot be retried after a reload '
          'without ordering a second scrape of the same catalogue',
    );
    expect(
      find.byKey(const ValueKey('pricing-run-attempt-storage-blocked')),
      findsOneWidget,
      reason: 'a silent refusal is indistinguishable from a broken button',
    );
    expect(
      tester
          .widget<FilledButton>(find.byKey(const ValueKey('pricing-run-start')))
          .onPressed,
      isNotNull,
      reason: 'the owner must be able to fix the storage and confirm again',
    );
  });

  test('the attempt id is randomness, not a position in this process', () async {
    const identity = 'run:batch-1:FULL_CATALOG:scope-hash:snapshot-hash';
    final ids = <String>{};
    for (var session = 0; session < 64; session += 1) {
      // Each iteration is an app session that kept nothing: a fresh browser
      // profile, a private window, a device that denied storage.
      SharedPreferences.setMockInitialValues({});
      final key = await PricingRunAttemptStore().reserve(identity);
      ids.add(key.split(':').last);
    }

    expect(
      ids.every((id) => RegExp(r'^[0-9a-f]{32}$').hasMatch(id)),
      isTrue,
      reason:
          'an attempt id has to be unguessable and globally unique; a counter '
          'in this process is neither, and two sessions both call their first '
          'run "1"',
    );
    expect(ids, hasLength(64));
  });
}

/// Drops the whole app — widget tree, provider container, cached preferences —
/// and brings it back the way a browser reload does, leaving only what was
/// actually written to storage.
Future<void> _reloadApp(WidgetTester tester, _RunBackend backend) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await tester.pump();
  SharedPreferences.resetStatic();
  await tester.pumpWidget(_app(backend));
  await tester.pumpAndSettle();
}

Future<void> _startAndConfirm(WidgetTester tester) async {
  await tester.tap(find.byKey(const ValueKey('pricing-run-start')));
  await tester.pumpAndSettle();
  await tester.tap(find.text('Запустить').last);
  // Bounded pumps: the start button holds a spinner while the request is in
  // flight, and `pumpAndSettle` would race that animation instead of the
  // request.
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 400));
  for (var i = 0; i < 8; i += 1) {
    await tester.pump();
  }
}

/// Хранилище, которое отвечает отказом на всё: приватное окно, запрещённые
/// данные сайта, платформа без бэкенда настроек.
class _UnavailableStorage implements PricingRunAttemptStorage {
  const _UnavailableStorage();

  @override
  Future<String?> read(String key) async => throw StateError('unavailable');

  @override
  Future<void> write(String key, String value) async =>
      throw StateError('unavailable');

  @override
  Future<void> remove(String key) async => throw StateError('unavailable');
}

Widget _app(_RunBackend backend, {PricingRunAttemptStorage? attemptStorage}) {
  return ProviderScope(
    overrides: [
      apiClientProvider.overrideWithValue(
        ApiClient(client: backend.client, baseUrl: 'https://api.example.test'),
      ),
      if (attemptStorage != null)
        pricingRunAttemptStoreProvider.overrideWithValue(
          PricingRunAttemptStore(storage: attemptStorage),
        ),
    ],
    child: MaterialApp(
      theme: AppTheme.light,
      locale: const Locale('ru'),
      supportedLocales: const [Locale('ru'), Locale('uk')],
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
      home: Scaffold(
        body: Center(
          child: PricingRunPanel(
            canAdministerWorkspace: true,
            onRunFinished: () {},
          ),
        ),
      ),
    ),
  );
}

class _RunBackend {
  _RunBackend({this.failFirstStart = false});

  final bool failFirstStart;
  final List<Map<String, dynamic>> startBodies = [];

  http.Client get client => MockClient((request) async {
    final path = request.url.path;
    if (request.method == 'GET' && path == '/api/v1/pricing/runs') {
      return _jsonResponse({
        'items': <Object>[],
        'total': 0,
        'limit': 25,
        'offset': 0,
      });
    }
    if (request.method == 'GET' && path == '/api/v1/catalog/imports') {
      return _jsonResponse(_importPage());
    }
    if (request.method == 'POST' && path == '/api/v1/pricing/runs/preview') {
      return _jsonResponse(_previewJson());
    }
    if (request.method == 'POST' && path == '/api/v1/pricing/runs') {
      startBodies.add(jsonDecode(request.body) as Map<String, dynamic>);
      if (failFirstStart && startBodies.length == 1) {
        return _jsonResponse({
          'detail': 'Pricing worker temporarily unavailable',
        }, statusCode: 503);
      }
      return _jsonResponse(_runJson('completed'), statusCode: 202);
    }
    if (request.method == 'GET' && path == '/api/v1/pricing/runs/run-1') {
      return _jsonResponse(_runJson('completed'));
    }
    return http.Response('not found', 404);
  });
}

http.Response _jsonResponse(Object payload, {int statusCode = 200}) {
  return http.Response(
    jsonEncode(payload),
    statusCode,
    headers: {'content-type': 'application/json'},
  );
}

Map<String, dynamic> _importPage() => {
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
};

Map<String, dynamic> _runJson(String status) => {
  'id': 'run-1',
  'import_batch_id': 'batch-1',
  'status': status,
  'coefficient_model': 'shrinkage',
  'coefficient_version': null,
  'calibration_dataset_hash': null,
  'calibration_accounting': <String, dynamic>{},
  'total_items': 10,
  'completed_items': 10,
  'failed_items': 0,
  'manual_review_items': 0,
  'cancel_requested': false,
  'error': null,
  'created_at': '2026-07-30T04:00:00Z',
};

Map<String, dynamic> _previewJson() => {
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
