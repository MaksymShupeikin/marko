import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/core/app_router.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/core/system_status.dart';
import 'package:marko_client/features/auth/auth_controller.dart';
import 'package:marko_client/features/auth/auth_models.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// The run binding is only worth anything end to end. The controller tests
/// prove `run_id` travels on each request in isolation, and the export test
/// proves the button reads the state — but the operator meets all of it at
/// once, on `/pricing`, through the real router: they read page one, a worker
/// finishes a newer calculation behind them, they press "показать ещё" and then
/// export. Page two and the file must both still describe the run whose rows
/// are on the screen, because that is the run they made their decisions from.
void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('page two and the export stay on the displayed run', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1400, 2200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final backend = _RunBackend();
    await tester.pumpWidget(_app(backend));
    await tester.pumpAndSettle();

    expect(
      find.text('Product rec-1'),
      findsOneWidget,
      reason: '/pricing must land on the recommendations of the newest run',
    );
    expect(backend.listQueries.first.containsKey('run_id'), isFalse);
    expect(backend.listQueries.first['offset'], '0');

    // A worker finishes a newer calculation while the operator reads page one.
    backend.newestRunId = 'run-2';

    final loadMore = find.textContaining('Показать ещё');
    await tester.ensureVisible(loadMore);
    await tester.pumpAndSettle();
    await tester.tap(loadMore);
    // Bounded pumps: the button holds a spinner while page two is in flight,
    // and `pumpAndSettle` would spin against that animation instead.
    await _flush(tester);

    expect(
      backend.listQueries.last['run_id'],
      'run-1',
      reason: 'page two must come from the run that produced page one',
    );
    expect(backend.listQueries.last['offset'], '2');
    expect(find.text('Product rec-3'), findsOneWidget);
    expect(
      find.text('Product new-1'),
      findsNothing,
      reason: 'rows from two calculations must never share one list',
    );

    final exportButton = find.byKey(const ValueKey('recommendations-export'));
    await tester.ensureVisible(exportButton);
    await tester.pumpAndSettle();
    await tester.tap(exportButton);
    await tester.pumpAndSettle();
    await tester.tap(find.text('CSV (.csv)'));
    // The saved bytes go through the platform file picker, which never answers
    // in a widget test; the request itself is already recorded by then.
    await _flush(tester);

    expect(backend.exportQueries, hasLength(1));
    expect(
      backend.exportQueries.single['run_id'],
      'run-1',
      reason:
          'the file the operator receives has to be the calculation they were '
          'reading, not whatever finished last',
    );
  });
}

Future<void> _flush(WidgetTester tester) async {
  await tester.pump();
  for (var i = 0; i < 8; i += 1) {
    await tester.pump(const Duration(milliseconds: 20));
  }
}

Widget _app(_RunBackend backend) {
  return ProviderScope(
    retry: (_, _) => null,
    overrides: [
      apiClientProvider.overrideWithValue(
        ApiClient(client: backend.client, baseUrl: 'http://api.test'),
      ),
      authControllerProvider.overrideWith(_SignedInAuthController.new),
      systemStatusProvider.overrideWith((ref) async => SystemHealth.active),
    ],
    child: Consumer(
      builder: (context, ref, _) {
        // The real router, entered at the real route the operator bookmarks.
        final router = ref.watch(appRouterProvider)..go('/pricing');
        return MaterialApp.router(
          theme: AppTheme.light,
          locale: const Locale('ru'),
          supportedLocales: const [Locale('ru'), Locale('uk')],
          localizationsDelegates: GlobalMaterialLocalizations.delegates,
          routerConfig: router,
        );
      },
    ),
  );
}

class _SignedInAuthController extends AuthController {
  @override
  Future<MarkoAuthState> build() async => const MarkoAuthState(
    user: AuthUser(
      id: 'user-1',
      email: 'owner@example.test',
      displayName: 'Owner',
      avatarUrl: null,
      workspaceId: 'workspace-1',
      workspaceRole: 'owner',
    ),
    busy: false,
    error: null,
    notice: null,
  );
}

/// A stand-in for the pricing router: `run_id` selects the run, and its absence
/// resolves to the newest one, exactly like `pricing_runs.list_recommendations`.
class _RunBackend {
  String newestRunId = 'run-1';
  final List<Map<String, String>> listQueries = [];
  final List<Map<String, String>> exportQueries = [];

  http.Client get client => MockClient((request) async {
    final path = request.url.path;
    final query = request.url.queryParameters;
    if (path == '/api/v1/pricing/recommendations') {
      listQueries.add(query);
      return _jsonResponse(
        _pageJson(query['run_id'] ?? newestRunId, int.parse(query['offset']!)),
      );
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
    if (path == '/api/v1/operations/discovery-funnel') {
      return _jsonResponse({'items': <Object>[]});
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

http.Response _jsonResponse(Object payload) => http.Response(
  jsonEncode(payload),
  200,
  headers: {'content-type': 'application/json'},
);
