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

/// "Запустить" used to mean one thing only: the whole catalogue. For a shop
/// with thousands of SKUs that is hours of scraping and the entire month's
/// budget, offered as the single available choice — so the operator either
/// takes it or does not run a calculation at all. A bounded cohort has to be
/// reachable, and its cost has to come from a preview of *that* cohort rather
/// than from arithmetic on the full-catalogue number.
void main() {
  // An outstanding run attempt outlives the widget, so the panel now needs
  // the platform storage it is written to.
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('a bounded cohort is previewed and started as its own scope', (
    tester,
  ) async {
    final backend = _ScopeBackend();
    await tester.pumpWidget(_app(backend));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const ValueKey('pricing-run-scope')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Первые 300 позиций').last);
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const ValueKey('pricing-run-start')));
    await tester.pumpAndSettle();

    expect(
      backend.previewBodies.single['scope_mode'],
      'EXPLICIT_ITEMS',
      reason: 'the chosen cohort is what must be priced, not the catalogue',
    );
    expect(
      (backend.previewBodies.single['catalog_item_ids'] as List).length,
      300,
      reason:
          'the backend contract names a bounded scope by its items; 300 of '
          'them arrive over two pages of the catalogue endpoint',
    );
    expect(backend.itemQueries.map((query) => query['offset']), ['0', '250']);

    expect(
      find.textContaining('первые 300 позиций импорта'),
      findsOneWidget,
      reason: 'the operator confirms a named scope, not "a calculation"',
    );
    expect(
      find.textContaining('позиций: 288'),
      findsOneWidget,
      reason: 'the estimate must be the bounded preview’s own answer',
    );
    expect(find.textContaining('около 15 мин'), findsOneWidget);
    expect(
      find.textContaining('позиций: 7000'),
      findsNothing,
      reason: 'the full-catalogue estimate does not describe this run',
    );
    expect(
      find.textContaining('около 120 мин'),
      findsNothing,
      reason:
          'showing the catalogue’s worst case for a 300-item run is exactly '
          'the number the operator is trying to avoid paying',
    );

    await tester.tap(find.text('Запустить').last);
    await _flush(tester);

    final start = backend.startBodies.single;
    expect(start['scope_mode'], 'EXPLICIT_ITEMS');
    expect((start['catalog_item_ids'] as List).length, 300);
    expect(
      start.containsKey('confirm_full_catalog'),
      isFalse,
      reason:
          'the backend rejects confirm_full_catalog on a bounded scope; this '
          'run is not the catalogue',
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('the whole catalogue stays available and stays confirmed', (
    tester,
  ) async {
    final backend = _ScopeBackend();
    await tester.pumpWidget(_app(backend));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const ValueKey('pricing-run-start')));
    await tester.pumpAndSettle();

    expect(backend.previewBodies.single['scope_mode'], 'FULL_CATALOG');
    expect(
      backend.itemQueries,
      isEmpty,
      reason:
          'a full-catalogue run does not enumerate the catalogue client-side',
    );
    expect(find.textContaining('весь каталог'), findsOneWidget);
    expect(find.textContaining('позиций: 7000'), findsOneWidget);

    await tester.tap(find.text('Запустить').last);
    await _flush(tester);

    final start = backend.startBodies.single;
    expect(start['scope_mode'], 'FULL_CATALOG');
    expect(
      start['confirm_full_catalog'],
      isTrue,
      reason: 'the most expensive mode still needs the owner to say so',
    );
    expect(start.containsKey('catalog_item_ids'), isFalse);
    expect(tester.takeException(), isNull);
  });
}

Future<void> _flush(WidgetTester tester) async {
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 400));
  for (var i = 0; i < 6; i += 1) {
    await tester.pump();
  }
}

Widget _app(_ScopeBackend backend) {
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

/// A 7000-SKU import. The bounded preview is deliberately *not* a fraction of
/// the full-catalogue one: only the server knows what is eligible, and a test
/// that let the two agree would pass on a client-side extrapolation.
class _ScopeBackend {
  final List<Map<String, dynamic>> previewBodies = [];
  final List<Map<String, dynamic>> startBodies = [];
  final List<Map<String, String>> itemQueries = [];

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
    if (request.method == 'GET' && path == '/api/v1/catalog/items') {
      final query = request.url.queryParameters;
      itemQueries.add(query);
      final limit = int.parse(query['limit']!);
      final offset = int.parse(query['offset']!);
      final count = (7000 - offset).clamp(0, limit);
      return _jsonResponse({
        'items': [for (var i = 0; i < count; i += 1) _itemJson(offset + i)],
        'total': 7000,
        'limit': limit,
        'offset': offset,
      });
    }
    if (request.method == 'POST' && path == '/api/v1/pricing/runs/preview') {
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      previewBodies.add(body);
      return _jsonResponse(
        body['scope_mode'] == 'EXPLICIT_ITEMS'
            ? _previewJson(
                scopeMode: 'EXPLICIT_ITEMS',
                requested: (body['catalog_item_ids'] as List).length,
                eligible: 288,
                excluded: 12,
                worstCaseSeconds: 900,
                requiresConfirmation: false,
              )
            : _previewJson(
                scopeMode: 'FULL_CATALOG',
                requested: 7000,
                eligible: 7000,
                excluded: 0,
                worstCaseSeconds: 7200,
                requiresConfirmation: true,
              ),
      );
    }
    if (request.method == 'POST' && path == '/api/v1/pricing/runs') {
      startBodies.add(jsonDecode(request.body) as Map<String, dynamic>);
      return _jsonResponse(_runJson('completed'), statusCode: 202);
    }
    if (request.method == 'GET' && path == '/api/v1/pricing/runs/run-1') {
      return _jsonResponse(_runJson('completed'));
    }
    return http.Response('not found', 404);
  });
}

Map<String, dynamic> _itemJson(int index) => {
  'id': 'item-$index',
  'import_batch_id': 'batch-1',
  'source_row': index + 2,
  'sku': 'SKU-$index',
  'oe_raw': 'OE$index',
  'oe_norm': 'OE$index',
  'mpn_raw': '',
  'mpn_norm': '',
  'name': 'Product $index',
  'category': 'brakes',
  'brand': null,
  'description': null,
  'product_url': null,
  'current_price': '100',
  'currency': 'UAH',
  'is_available': true,
  'is_owned': true,
  'stock_status': 'fresh',
  'stock_qty': null,
  'stock_age_days': null,
  'expected_units_sold': null,
  'cost_configured': false,
  'cost_privacy_mode': 'plain',
};

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
      'total_rows': 7000,
      'imported_rows': 7000,
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
  'total_items': 288,
  'completed_items': 288,
  'failed_items': 0,
  'manual_review_items': 0,
  'cancel_requested': false,
  'error': null,
  'created_at': '2026-07-30T04:00:00Z',
};

Map<String, dynamic> _previewJson({
  required String scopeMode,
  required int requested,
  required int eligible,
  required int excluded,
  required int worstCaseSeconds,
  required bool requiresConfirmation,
}) => {
  'scope_contract_version': 'v1',
  'import_batch_id': 'batch-1',
  'scope_mode': scopeMode,
  'policy_version': 'test-v1',
  'catalog_snapshot_hash': 'a' * 64,
  'scope_hash': (scopeMode == 'FULL_CATALOG' ? 'b' : 'c') * 64,
  'preview_token': 'mrp1_testtoken0000000000000000000000000000',
  'requires_full_catalog_confirmation': requiresConfirmation,
  'estimate': {
    'requested_items': requested,
    'eligible_items': eligible,
    'excluded_items': excluded,
    'unique_scrape_inputs': eligible,
    'duplicate_items': 0,
    'worst_case_duration_seconds': worstCaseSeconds,
  },
  'exclusions': <Map<String, dynamic>>[],
  'exclusions_truncated': false,
  'scope_manifest': <String, dynamic>{},
};
