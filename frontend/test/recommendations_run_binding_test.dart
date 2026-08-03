import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/pricing/pricing_api.dart';
import 'package:marko_client/features/pricing/pricing_controller.dart';
import 'package:marko_client/features/pricing/recommendations_page.dart';

/// A pricing screen shows one calculation. The backend falls back to the newest
/// run whenever `run_id` is missing, so a run that finishes while the operator
/// is reading page one used to redirect page two, the counters and the export
/// to a different calculation — silently, under unchanged rows.
void main() {
  test('page two stays on the run that produced page one', () async {
    final backend = _RunBackend();
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
    // The worker finishes a newer run while the operator reads page one.
    backend.newestRunId = 'run-2';
    await container.read(recommendationsControllerProvider.notifier).loadMore();
    final state = container
        .read(recommendationsControllerProvider)
        .requireValue;

    expect(
      backend.listQueries.last['run_id'],
      'run-1',
      reason: 'page two must be requested from the run page one came from',
    );
    expect(state.page.items.map((item) => item.id), [
      'rec-1',
      'rec-2',
      'rec-3',
    ]);
    expect(state.page.runId, 'run-1');
    expect(
      state.page.total,
      3,
      reason: 'the total belongs to the displayed run',
    );
    expect(
      state.page.actionCounts.raise,
      3,
      reason: 'the summary tiles must not count another run’s rows',
    );
  });

  test('an explicit refresh stays on the displayed run', () async {
    final backend = _RunBackend();
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
    backend.newestRunId = 'run-2';
    await container.read(recommendationsControllerProvider.notifier).refresh();
    final state = container
        .read(recommendationsControllerProvider)
        .requireValue;

    expect(backend.listQueries.last['run_id'], 'run-1');
    expect(state.page.runId, 'run-1');

    // Moving to the new run is a deliberate act, and it replaces the view.
    await container
        .read(recommendationsControllerProvider.notifier)
        .showLatestRun();
    final latest = container
        .read(recommendationsControllerProvider)
        .requireValue;

    expect(backend.listQueries.last.containsKey('run_id'), isFalse);
    expect(latest.runId, 'run-2');
    expect(latest.page.items.map((item) => item.id), ['new-1']);
  });

  test('a page from another run is never merged into the list', () async {
    // A backend that ignores run_id — a stale deployment or a proxy that drops
    // the parameter — must not be able to splice two runs into one list.
    final backend = _RunBackend(ignoreRunId: true);
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
    backend.newestRunId = 'run-2';
    await container.read(recommendationsControllerProvider.notifier).loadMore();
    final state = container
        .read(recommendationsControllerProvider)
        .requireValue;

    expect(state.page.items.map((item) => item.id), ['rec-1', 'rec-2']);
    expect(state.page.runId, 'run-1');
    expect(
      state.newerRunAvailable,
      isTrue,
      reason: 'refusing the page silently would look like a dead button',
    );
    expect(state.isLoadingMore, isFalse);
  });

  testWidgets('the export downloads the run that is on screen', (tester) async {
    final backend = _RunBackend();
    await tester.pumpWidget(
      ProviderScope(
        retry: (_, _) => null,
        overrides: [
          apiClientProvider.overrideWithValue(
            ApiClient(client: backend.client, baseUrl: 'http://api.test'),
          ),
        ],
        child: MaterialApp(
          theme: AppTheme.light,
          locale: const Locale('ru'),
          supportedLocales: const [Locale('ru'), Locale('uk')],
          localizationsDelegates: GlobalMaterialLocalizations.delegates,
          home: const Scaffold(body: RecommendationsPage()),
        ),
      ),
    );
    await tester.pumpAndSettle();

    // A newer run lands while the operator is looking at run-1.
    backend.newestRunId = 'run-2';

    await tester.tap(find.byKey(const ValueKey('recommendations-export')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('CSV (.csv)'));
    // Bounded pumps: saving the received bytes goes through the platform file
    // picker, which never answers in a widget test. The request itself is
    // already recorded by then.
    for (var i = 0; i < 6; i += 1) {
      await tester.pump(const Duration(milliseconds: 20));
    }

    expect(backend.exportQueries, hasLength(1));
    expect(
      backend.exportQueries.single['run_id'],
      'run-1',
      reason:
          'the file the operator receives must be the calculation they were '
          'reading, not whatever finished last',
    );
  });
}

/// A stand-in for the pricing router: `run_id` selects the run, and its absence
/// resolves to the newest one, exactly like `pricing_runs.list_recommendations`.
class _RunBackend {
  _RunBackend({this.ignoreRunId = false});

  final bool ignoreRunId;
  String newestRunId = 'run-1';
  final List<Map<String, String>> listQueries = [];
  final List<Map<String, String>> exportQueries = [];

  http.Client get client => MockClient((request) async {
    final path = request.url.path;
    final query = request.url.queryParameters;
    if (path == '/api/v1/pricing/recommendations') {
      listQueries.add(query);
      final runId = ignoreRunId ? newestRunId : query['run_id'] ?? newestRunId;
      return _jsonResponse(_pageJson(runId, int.parse(query['offset'] ?? '0')));
    }
    if (path == '/api/v1/pricing/recommendations/export') {
      exportQueries.add(query);
      return http.Response.bytes(
        [0x69, 0x64],
        200,
        headers: {
          'content-type': 'text/csv',
          'content-disposition': 'attachment; filename="run.csv"',
          'x-export-row-count': '3',
        },
      );
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

Map<String, dynamic> _pageJson(String runId, int offset) {
  final rows = switch ((runId, offset)) {
    ('run-1', 0) => ['rec-1', 'rec-2'],
    ('run-1', _) => ['rec-3'],
    ('run-2', 0) => ['new-1'],
    _ => <String>[],
  };
  return {
    'items': rows.map((id) => _recommendationJson(id, runId)).toList(),
    'total': runId == 'run-1' ? 3 : 1,
    'run_id': runId,
    'limit': 2,
    'offset': offset,
    'action_counts': {
      'raise': runId == 'run-1' ? 3 : 9,
      'lower': 0,
      'review': 0,
      'hold': 0,
      'total': runId == 'run-1' ? 3 : 9,
    },
  };
}

Map<String, dynamic> _recommendationJson(String id, String runId) => {
  'id': id,
  'pricing_run_id': runId,
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

http.Response _jsonResponse(Object payload) {
  return http.Response(
    jsonEncode(payload),
    200,
    headers: {'content-type': 'application/json'},
  );
}
