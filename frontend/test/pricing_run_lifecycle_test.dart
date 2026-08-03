import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/pricing/pricing_models.dart';
import 'package:marko_client/features/pricing/pricing_run_panel.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// The happy path of a pricing run finishes on the first poll, so it never
/// exercises the state the operator actually sits in: a run that stays active
/// for minutes. These tests keep the run non-terminal on purpose.
void main() {
  // An outstanding run attempt outlives the widget, so the panel now needs
  // the platform storage it is written to.
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('cancel stays available while the started run is still polling', (
    tester,
  ) async {
    final firstStatus = Completer<http.Response>();
    var statusFetches = 0;
    var cancelPosts = 0;
    var finishedCallbacks = 0;
    final client = MockClient((request) async {
      final path = request.url.path;
      if (request.method == 'GET' && path == '/api/v1/pricing/runs') {
        return _jsonResponse(_emptyRunPage());
      }
      if (request.method == 'GET' && path == '/api/v1/catalog/imports') {
        return _jsonResponse(_importPage());
      }
      if (request.method == 'POST' && path == '/api/v1/pricing/runs/preview') {
        return _jsonResponse(_previewJson());
      }
      if (request.method == 'POST' && path == '/api/v1/pricing/runs') {
        return _jsonResponse(_runJson('running'), statusCode: 202);
      }
      if (request.method == 'POST' &&
          path == '/api/v1/pricing/runs/run-1/cancel') {
        cancelPosts += 1;
        return _jsonResponse(_runJson('running', cancelRequested: true));
      }
      if (request.method == 'GET' && path == '/api/v1/pricing/runs/run-1') {
        statusFetches += 1;
        // The first status read never resolves until the test says so, which
        // holds the panel inside an active poll deterministically.
        if (statusFetches == 1) return firstStatus.future;
        return _jsonResponse(_runJson('cancelled', cancelRequested: true));
      }
      return http.Response('not found', 404);
    });

    await tester.pumpWidget(
      _app(
        client: client,
        child: PricingRunPanel(
          canAdministerWorkspace: true,
          onRunFinished: () => finishedCallbacks += 1,
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const ValueKey('pricing-run-start')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Запустить').last);
    await _confirmAndFlush(tester);

    expect(statusFetches, 1, reason: 'the run must be polled after start');
    expect(
      _buttonAt(tester, 'pricing-run-cancel'),
      isNotNull,
      reason:
          'polling is not a mutation: the operator must be able to stop a '
          'run that is still working',
    );
    expect(
      _buttonAt(tester, 'pricing-run-start'),
      isNull,
      reason: 'a second run must not be startable on top of an active one',
    );

    await tester.tap(find.byKey(const ValueKey('pricing-run-cancel')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Отменить расчёт').last);
    await _confirmAndFlush(tester);

    expect(cancelPosts, 1);
    expect(
      find.textContaining('Отмена запрошена'),
      findsOneWidget,
      reason:
          'the backend only flags cancel_requested; the run keeps working '
          'until the worker notices, and the operator must see that',
    );
    expect(
      _buttonAt(tester, 'pricing-run-cancel'),
      isNull,
      reason: 'cancelling twice sends a second useless request',
    );
    expect(finishedCallbacks, 0);

    firstStatus.complete(
      _jsonResponse(_runJson('cancelled', cancelRequested: true)),
    );
    await tester.pumpAndSettle();

    expect(find.text('Расчёт отменён'), findsOneWidget);
    expect(finishedCallbacks, 1);
    expect(tester.takeException(), isNull);
  });

  testWidgets('reloading a page with an unfinished run resumes polling', (
    tester,
  ) async {
    var statusFetches = 0;
    var finishedCallbacks = 0;
    final client = MockClient((request) async {
      final path = request.url.path;
      if (request.method == 'GET' && path == '/api/v1/pricing/runs') {
        return _jsonResponse({
          'items': [_runJson('running')],
          'total': 1,
          'limit': 25,
          'offset': 0,
        });
      }
      if (request.method == 'GET' && path == '/api/v1/catalog/imports') {
        return _jsonResponse(_importPage());
      }
      if (request.method == 'GET' && path == '/api/v1/pricing/runs/run-1') {
        statusFetches += 1;
        return _jsonResponse(_runJson('completed'));
      }
      return http.Response('not found', 404);
    });

    await tester.pumpWidget(
      _app(
        client: client,
        child: PricingRunPanel(
          canAdministerWorkspace: true,
          onRunFinished: () => finishedCallbacks += 1,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(
      statusFetches,
      1,
      reason:
          'a run left active by an earlier session must keep updating without '
          'a manual "Обновить статус"',
    );
    expect(find.text('Расчёт завершён'), findsOneWidget);
    expect(finishedCallbacks, 1);
    expect(tester.takeException(), isNull);
  });

  test('a run summary carries the backend cancel_requested flag', () {
    final requested = PricingRunSummary.fromJson(
      _runJson('running', cancelRequested: true),
    );
    expect(requested.cancelRequested, isTrue);
    expect(requested.isFinished, isFalse);
    expect(
      requested.isCancellable,
      isFalse,
      reason: 'a cancel already asked for cannot be asked for again',
    );

    final active = PricingRunSummary.fromJson(_runJson('running'));
    expect(active.cancelRequested, isFalse);
    expect(active.isCancellable, isTrue);

    // Older payloads and fixtures omit the field entirely.
    final legacy = Map<String, dynamic>.from(_runJson('running'))
      ..remove('cancel_requested');
    expect(PricingRunSummary.fromJson(legacy).cancelRequested, isFalse);
  });
}

/// Closes a confirmation dialog and lets the queued HTTP futures resolve
/// without settling: `pumpAndSettle` would keep advancing the clock through the
/// whole polling schedule, which is exactly the window under test here.
Future<void> _confirmAndFlush(WidgetTester tester) async {
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 400));
  for (var i = 0; i < 4; i += 1) {
    await tester.pump();
  }
}

ButtonStyleButton? _findButton(WidgetTester tester, String key) {
  final finder = find.byKey(ValueKey(key));
  if (finder.evaluate().isEmpty) return null;
  return tester.widget<ButtonStyleButton>(finder);
}

/// Returns the button's `onPressed`, or `null` when the button is missing or
/// disabled — both mean "the operator cannot act".
VoidCallback? _buttonAt(WidgetTester tester, String key) =>
    _findButton(tester, key)?.onPressed;

Widget _app({required http.Client client, required Widget child}) {
  return ProviderScope(
    overrides: [
      apiClientProvider.overrideWithValue(
        ApiClient(client: client, baseUrl: 'https://api.example.test'),
      ),
    ],
    child: MaterialApp(
      theme: AppTheme.light,
      locale: const Locale('ru'),
      supportedLocales: const [Locale('ru'), Locale('uk')],
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
      home: Scaffold(body: Center(child: child)),
    ),
  );
}

http.Response _jsonResponse(Object payload, {int statusCode = 200}) {
  return http.Response(
    jsonEncode(payload),
    statusCode,
    headers: {'content-type': 'application/json'},
  );
}

Map<String, dynamic> _emptyRunPage() => {
  'items': <Object>[],
  'total': 0,
  'limit': 25,
  'offset': 0,
};

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

Map<String, dynamic> _runJson(String status, {bool cancelRequested = false}) =>
    {
      'id': 'run-1',
      'import_batch_id': 'batch-1',
      'status': status,
      'coefficient_model': 'shrinkage',
      'coefficient_version': null,
      'calibration_dataset_hash': null,
      'calibration_accounting': {'correlation_id': 'corr-run-1'},
      'total_items': 10,
      'completed_items': status == 'completed' ? 10 : 2,
      'failed_items': 0,
      'manual_review_items': 1,
      'cancel_requested': cancelRequested,
      'error': null,
      'created_at': '2026-07-30T04:00:00Z',
    };

/// Предпросмотр области: запуск теперь замораживает её до подтверждения.
Map<String, dynamic> _previewJson({
  int eligible = 3,
  int excluded = 0,
  bool requiresConfirmation = true,
}) {
  return {
    'scope_contract_version': 'v1',
    'import_batch_id': 'batch-1',
    'scope_mode': 'FULL_CATALOG',
    'policy_version': 'test-v1',
    'catalog_snapshot_hash': 'a' * 64,
    'scope_hash': 'b' * 64,
    'preview_token': 'mrp1_testtoken0000000000000000000000000000',
    'requires_full_catalog_confirmation': requiresConfirmation,
    'estimate': {
      'requested_items': eligible + excluded,
      'eligible_items': eligible,
      'excluded_items': excluded,
      'unique_scrape_inputs': eligible,
      'duplicate_items': 0,
      'worst_case_duration_seconds': 120,
    },
    'exclusions': <Map<String, dynamic>>[],
    'exclusions_truncated': false,
    'scope_manifest': <String, dynamic>{},
  };
}
