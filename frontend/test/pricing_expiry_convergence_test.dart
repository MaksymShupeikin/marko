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
import 'package:marko_client/core/widgets/marko_menu.dart';
import 'package:marko_client/features/pricing/pricing_run_panel.dart';
import 'package:marko_client/features/pricing/recommendations_page.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Одна мёртвая сессия — один ответ, на каком бы запросе она ни всплыла.
///
/// Эти пути остались вне общей классификации: доказательства, replay, уточнение
/// tier, разметка сопоставимости и её перепроверка, воронка discovery и
/// fitment. Каждый из них показывал английскую строку бэкенда — в снекбаре,
/// который уедет через четыре секунды, или в красной строке рядом с «Повторить»,
/// который может только снова не сработать. Экспорт при этом оставался
/// нажимаемым, а стартовая загрузка панели теряла второй отказ из двух.
void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('every pricing path converges on the one session-expired state', () {
    testWidgets('the evidence load', (tester) async {
      final harness = await _open(tester, expire: {'evidence'});

      expect(
        find.textContaining('Не удалось загрузить доказательства'),
        findsNothing,
        reason:
            'the evidence is not missing — the credential is, and only a '
            'sign-in brings it back',
      );
      await _expectAnsweredOnce(tester, harness);
    });

    testWidgets('the replay verification', (tester) async {
      final harness = await _open(tester, expire: {'replay'});
      await _tapText(tester, 'Проверить replay');

      expect(find.textContaining('Replay недоступен'), findsNothing);
      await _expectAnsweredOnce(tester, harness);
    });

    testWidgets('the tier override', (tester) async {
      final harness = await _open(tester, expire: {'tier'});
      await _tapTooltip(tester, 'Уточнить tier');
      await tester.enterText(
        find.byType(TextField).last,
        'OEM подтверждён каталогом',
      );
      await _tapText(tester, 'Сохранить');

      expect(find.textContaining('Не удалось сохранить:'), findsNothing);
      await _expectAnsweredOnce(tester, harness);
    });

    testWidgets('the comparability feedback', (tester) async {
      final harness = await _open(tester, expire: {'feedback'});
      await _tapText(tester, 'Подтвердить / исправить');
      await tester.enterText(find.byType(TextField).last, 'Тот же артикул');
      await _tapText(tester, 'Сохранить');

      expect(
        find.textContaining('Не удалось сохранить проверку'),
        findsNothing,
      );
      await _expectAnsweredOnce(tester, harness);
    });

    testWidgets('the comparability re-review', (tester) async {
      final harness = await _open(tester, expire: {'review'});
      await _tapText(tester, 'Проверить заново');

      expect(
        find.textContaining('Не удалось сохранить проверку'),
        findsNothing,
      );
      await _expectAnsweredOnce(tester, harness);
    });

    testWidgets('the discovery funnel', (tester) async {
      final harness = await _open(tester, expire: {'funnel'});
      await _tapText(tester, 'Почему конкуренты не попали в расчёт');

      expect(
        find.text('Повторить'),
        findsNothing,
        reason: 'repeating the request with the same dead token cannot work',
      );
      await _expectAnsweredOnce(tester, harness);
    });

    testWidgets('the fitment panel', (tester) async {
      final harness = await _open(tester, expire: {'fitment-candidates'});

      expect(
        find.textContaining('Fitment intelligence недоступен'),
        findsNothing,
      );
      await _expectAnsweredOnce(tester, harness);
    });
  });

  testWidgets('the export stops offering a download the session cannot make', (
    tester,
  ) async {
    final harness = await _open(tester, expire: {});
    harness.backend.expire.add('list');
    await tester.tap(find.byTooltip('Обновить'));
    await _flush(tester);

    final exportButton = find.byKey(const ValueKey('recommendations-export'));
    expect(
      tester.widget<MarkoMenuButton<String>>(exportButton).enabled,
      isFalse,
      reason:
          'an export on a dead token can only produce another 401, and the '
          'operator has already been told what to do about it',
    );
    await tester.tap(exportButton);
    await _flush(tester);
    expect(
      find.text('Excel (.xlsx)'),
      findsNothing,
      reason: 'a disabled control must not open its menu',
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('two initial requests can both fail without an orphan', (
    tester,
  ) async {
    // The panel starts the run list and the import list together. Awaiting them
    // one after the other means the second rejection has nobody waiting on it
    // by the time the first one throws.
    final backend = _ConvergenceBackend()..expire.addAll({'runs', 'imports'});
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
            body: PricingRunPanel(
              canAdministerWorkspace: true,
              onRunFinished: () {},
            ),
          ),
        ),
      ),
    );
    await _flush(tester, rounds: 16);

    expect(
      tester.takeException(),
      isNull,
      reason:
          'the second 401 has no handler and surfaces as an unhandled async '
          'error, which is how a dead session turns into a crash report',
    );
    expect(
      find.byKey(const ValueKey('pricing-run-session-expired')),
      findsOneWidget,
    );
    expect(find.textContaining('Authentication required'), findsNothing);
  });
}

/// Один ответ — и ровно один.
Future<void> _expectAnsweredOnce(WidgetTester tester, _Harness harness) async {
  expect(
    find.textContaining('Authentication required'),
    findsNothing,
    reason: 'a backend English string is not an answer for a shop owner',
  );
  expect(
    find.textContaining('Сессия истекла'),
    findsOneWidget,
    reason: 'two copies read as two problems, and none reads as none',
  );

  final reauthenticate = find.byKey(const ValueKey('marko-reauthenticate'));
  expect(reauthenticate, findsOneWidget);
  await tester.ensureVisible(reauthenticate);
  await _flush(tester);
  await tester.tap(reauthenticate);
  await _flush(tester);
  expect(
    harness.auth.logouts,
    1,
    reason: 'dropping the dead credential is what re-opens the sign-in screen',
  );
  expect(tester.takeException(), isNull);
}

Future<void> _tapText(WidgetTester tester, String label) async {
  final finder = find.text(label).first;
  await tester.ensureVisible(finder);
  await _flush(tester);
  await tester.tap(finder, warnIfMissed: false);
  await _flush(tester);
}

Future<void> _tapTooltip(WidgetTester tester, String tooltip) async {
  final finder = find.byTooltip(tooltip).first;
  await tester.ensureVisible(finder);
  await _flush(tester);
  await tester.tap(finder, warnIfMissed: false);
  await _flush(tester);
}

class _Harness {
  _Harness(this.backend, this.auth);

  final _ConvergenceBackend backend;
  final _RecordingAuthClient auth;
}

Future<_Harness> _open(
  WidgetTester tester, {
  required Set<String> expire,
}) async {
  tester.view.physicalSize = const Size(1600, 9000);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final backend = _ConvergenceBackend()..expire.addAll(expire);
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
            // Раскрытая карточка — единственный способ увидеть доказательства,
            // replay, tier и fitment без ручного разворачивания.
            initialRecommendationId: 'rec-1',
          ),
        ),
      ),
    ),
  );
  // Ограниченные помпы: живой прогон анимирует индикатор, и `pumpAndSettle`
  // гонялся бы за анимацией вместо состояния.
  await _flush(tester, rounds: 20);
  return _Harness(backend, auth);
}

Future<void> _flush(WidgetTester tester, {int rounds = 8}) async {
  await tester.pump();
  for (var i = 0; i < rounds; i += 1) {
    await tester.pump(const Duration(milliseconds: 20));
  }
}

/// Бэкенд, у которого сессия умирает ровно на названном запросе.
class _ConvergenceBackend {
  final Set<String> expire = {};

  http.Client get client => MockClient((request) async {
    final path = request.url.path;
    final method = request.method;
    final name = switch (path) {
      '/api/v1/pricing/recommendations' => 'list',
      '/api/v1/pricing/recommendations/export' => 'export',
      '/api/v1/pricing/runs' => method == 'POST' ? 'start' : 'runs',
      '/api/v1/pricing/runs/preview' => 'preview',
      '/api/v1/pricing/runs/run-1' => 'poll',
      '/api/v1/catalog/imports' => 'imports',
      '/api/v1/operations/discovery-funnel' => 'funnel',
      _ when path.endsWith('/evidence') => 'evidence',
      _ when path.endsWith('/replay') => 'replay',
      _ when path.endsWith('/tier-overrides') => 'tier',
      _ when path.endsWith('/feedback') => 'feedback',
      _ when path.endsWith('/comparability-reviews') => 'review',
      _ when path.endsWith('/candidates') => 'fitment-candidates',
      _ when path.endsWith('/recommendation') => 'fitment-recommendation',
      _ when path.startsWith('/api/v1/pricing/recommendations/') =>
        'recommendation',
      _ => 'other',
    };
    if (expire.contains(name)) {
      return _json({'detail': 'Authentication required'}, statusCode: 401);
    }
    switch (name) {
      case 'list':
        return _json({
          'items': [_recommendation('rec-1')],
          'total': 1,
          'run_id': 'run-1',
          'limit': 50,
          'offset': 0,
          'action_counts': {
            'raise': 1,
            'lower': 0,
            'review': 0,
            'hold': 0,
            'total': 1,
          },
        });
      case 'recommendation':
        return _json(_recommendation('rec-1'));
      case 'runs':
        return _json({
          'items': <Object>[],
          'total': 0,
          'limit': 25,
          'offset': 0,
        });
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
      case 'evidence':
        return _json([_evidence()]);
      case 'replay':
        return _json({
          'recommendation_id': 'rec-1',
          'contract_version': 'v1',
          'exact_match': true,
          'mismatches': <String, dynamic>{},
        });
      case 'tier':
      case 'other':
        return _json(<String, dynamic>{});
      case 'feedback':
      case 'review':
        return _json(_review());
      case 'funnel':
        return _json({
          'sampled_runs': 0,
          'total_candidates': 0,
          'gates': <String, dynamic>{},
          'categories': <Object>[],
        });
      case 'fitment-candidates':
        return _json({
          'items': <Object>[],
          'total': 0,
          'analysis_id': null,
          'limit': 250,
          'offset': 0,
        });
      case 'fitment-recommendation':
        return _json({'detail': 'not found'}, statusCode: 404);
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

Map<String, dynamic> _review() => {
  'review_id': 'review-1',
  'market_observation_id': 'obs-1',
  'input_hash': 'abc',
  'verdict': 'COMPARABLE',
  'match_level': 'ACCEPTABLE_ANALOGUE',
  'confidence': '0.94',
  'rationale': 'OE and part type agree.',
  'dimension_findings': <Object>[],
  'hard_stop_conflicts': <Object>[],
  'decision_source': 'LLM',
  'status': 'COMPLETED',
  'provider': 'openai_responses',
  'model_id': 'gpt-test',
  'prompt_version': 'comparability-v1',
  'reviewed_at': '2026-07-31T12:00:00Z',
  'cache_hit_review_id': null,
  'image_urls': <Object>[],
  'provider_response_id': 'resp-1',
  'error_code': null,
  'error_detail': null,
  'feedback_count': 0,
  'latest_feedback_id': null,
  'latest_feedback_decision': null,
  'latest_feedback_reason': null,
  'pricing_eligible': true,
};

Map<String, dynamic> _evidence() => {
  'observation_id': 'obs-1',
  'seller_name': 'Seller',
  'title': 'Brake disc',
  'url': 'https://example.test/item',
  'price': '1000',
  'currency': 'UAH',
  'tier': 'budget',
  'is_dumping': false,
  'observed_at': '2026-07-31T12:00:00Z',
  'llm_review_required': true,
  'llm_pricing_eligible': true,
  'llm_review': _review(),
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
