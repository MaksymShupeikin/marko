import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/pricing/pricing_run_panel.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// The idempotency key answers exactly one question: "is this the same attempt
/// as the last one?". Deriving it from the import and the scope hash alone
/// answers a different one — "is this the same scope?" — and the scope of a
/// deliberate re-run is, of course, identical. The backend then returns the
/// original run and the operator sees yesterday's numbers with no error and no
/// explanation for why a fresh calculation never happened.
void main() {
  // An outstanding attempt outlives the widget, so the panel now needs the
  // platform storage it is written to.
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('a deliberate second run of the same scope is not deduplicated', (
    tester,
  ) async {
    final backend = _RunBackend();
    await tester.pumpWidget(_app(backend));
    await tester.pumpAndSettle();

    await _startAndConfirm(tester);
    expect(backend.startBodies, hasLength(1));
    expect(find.text('Расчёт завершён'), findsOneWidget);

    // The operator changed a cost, an override or a competitor and now wants
    // the very same catalogue recalculated.
    await _startAndConfirm(tester);

    expect(backend.startBodies, hasLength(2));
    expect(
      backend.startBodies.first['idempotency_key'],
      isNot(backend.startBodies.last['idempotency_key']),
      reason:
          'a key derived from batch+scope makes every later re-run of the same '
          'catalogue collapse onto the first run, silently',
    );
    expect(
      backend.startBodies.map((body) => body['expected_scope_hash']).toSet(),
      hasLength(1),
      reason: 'the scope really is identical — only the attempt is new',
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('retrying a start that failed reuses the same key', (
    tester,
  ) async {
    final backend = _RunBackend(failFirstStart: true);
    await tester.pumpWidget(_app(backend));
    await tester.pumpAndSettle();

    await _startAndConfirm(tester);
    expect(backend.startBodies, hasLength(1));
    expect(
      find.textContaining('temporarily unavailable'),
      findsOneWidget,
      reason: 'a failed start has to say so before the operator retries it',
    );

    // A start that failed may still have created the run: the response is what
    // was lost, not necessarily the work. Retrying the same confirmed scope
    // must therefore be the *same* attempt.
    await _startAndConfirm(tester);

    expect(backend.startBodies, hasLength(2));
    expect(
      backend.startBodies.first['idempotency_key'],
      backend.startBodies.last['idempotency_key'],
      reason:
          'a fresh key on every attempt turns one lost response into two real '
          'runs of the whole catalogue',
    );
    expect(tester.takeException(), isNull);
  });
}

Future<void> _startAndConfirm(WidgetTester tester) async {
  await tester.tap(find.byKey(const ValueKey('pricing-run-start')));
  await tester.pumpAndSettle();
  await tester.tap(find.text('Запустить').last);
  // Bounded pumps: the start button holds a spinner while the request is in
  // flight, and `pumpAndSettle` would race it instead of the request.
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 400));
  for (var i = 0; i < 6; i += 1) {
    await tester.pump();
  }
}

Widget _app(_RunBackend backend) {
  return ProviderScope(
    overrides: [
      apiClientProvider.overrideWithValue(
        ApiClient(client: backend.client, baseUrl: 'https://api.example.test'),
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

/// The scope of a re-run is identical by construction: same import, same
/// catalogue, same policy — so the hashes never move.
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
