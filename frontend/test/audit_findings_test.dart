// Аудит 2026-07-27: доказательства UI-находок (§4 вариации 17-26).
//
// Файл создан агентом-аудитором согласно CONSTRAINT_6(a).
// После remediation тесты фиксируют исправленное поведение Wave 0.

import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/core/app_language.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/core/presentation_formatters.dart';
import 'package:marko_client/core/system_status.dart';
import 'package:marko_client/core/widgets/marko_button.dart';
import 'package:marko_client/features/auth/auth_controller.dart';
import 'package:marko_client/features/auth/auth_models.dart';
import 'package:marko_client/features/auth/auth_page.dart';
import 'package:marko_client/features/attention/attention_controller.dart';
import 'package:marko_client/features/attention/attention_models.dart';
import 'package:marko_client/features/catalog/catalog_api.dart';
import 'package:marko_client/features/catalog/catalog_controller.dart';
import 'package:marko_client/features/catalog/catalog_models.dart';
import 'package:marko_client/features/catalog/catalog_page.dart';
import 'package:marko_client/features/catalog/widgets/catalog_product_details_sheet.dart';
import 'package:marko_client/features/dashboard/dashboard_page.dart';
import 'package:marko_client/features/fitment/fitment_api.dart';
import 'package:marko_client/features/fitment/fitment_candidates_panel.dart';
import 'package:marko_client/features/fitment/fitment_controller.dart';
import 'package:marko_client/features/fitment/fitment_models.dart';
import 'package:marko_client/features/fitment/fitment_recommendation_card.dart';
import 'package:marko_client/features/pricing/catalog_context_dialog.dart';
import 'package:marko_client/features/pricing/pricing_controller.dart';
import 'package:marko_client/features/pricing/pricing_models.dart';
import 'package:marko_client/features/pricing/recommendations_page.dart';
import 'package:marko_client/features/pricing/recommendation_decision_dialog.dart';
import 'package:marko_client/features/pricing/tier_override_dialog.dart';
import 'package:marko_client/features/stores/store_models.dart';
import 'package:marko_client/features/stores/store_products_page.dart';
import 'package:marko_client/features/stores/stores_controller.dart';
import 'package:marko_client/features/stores/stores_page.dart';

Map<String, dynamic> _recommendationJson({
  String action = 'RAISE',
  String recommendedPrice = '1234.567',
  String currentPrice = '1000.00',
  String currency = 'UAH',
  List<String> reasonCodes = const ['LOW_DISPERSION'],
}) {
  return <String, dynamic>{
    'id': 'rec-1',
    'pricing_run_id': 'run-1',
    'catalog_snapshot_id': 'snap-1',
    'catalog_item_id': 'item-1',
    'sku': 'SKU-1',
    'oe_norm': '0986424815',
    'name': 'Brake pad set',
    'category': 'brake_pads',
    'stock_status': 'fresh',
    'action': action,
    'current_price': currentPrice,
    'recommended_price': recommendedPrice,
    'confidence': '0.71',
    'confidence_grade': 'B',
    'competitor_count': 5,
    'priority_score': '1234.5',
    'priority_score_type': 'gross_uplift_opportunity',
    'reason_codes': reasonCodes,
    'currency': currency,
    'price_tick': '0.50',
    'computed_at': '2026-07-27T10:00:00Z',
  };
}

void main() {
  group('§4 вариация 22: null в необязательных полях', () {
    test('AUDIT: PricingRecommendation парсится при минимальном ответе', () {
      final item = PricingRecommendation.fromJson(_recommendationJson());
      expect(item.recommendedPrice, DecimalValue.parse('1234.567'));
      expect(item.priceTick, DecimalValue.parse('0.5'));
      expect(item.currency, 'UAH');
      expect(item.fairPrice, isNull);
    });

    test('REGRESSION: отсутствие reason_codes даёт typed contract error', () {
      final json = _recommendationJson()..remove('reason_codes');
      expect(
        () => PricingRecommendation.fromJson(json),
        throwsA(
          isA<FormatException>().having(
            (error) => error.message,
            'message',
            contains('reason_codes'),
          ),
        ),
      );
    });

    test(
      'REGRESSION: отсутствие competitor_count даёт typed contract error',
      () {
        final json = _recommendationJson()..remove('competitor_count');
        expect(
          () => PricingRecommendation.fromJson(json),
          throwsA(
            isA<FormatException>().having(
              (error) => error.message,
              'message',
              contains('competitor_count'),
            ),
          ),
        );
      },
    );
  });

  group('Округление денег и валюта', () {
    testWidgets('REGRESSION: цена квантуется по tick и сохраняет валюту', (
      tester,
    ) async {
      final item = PricingRecommendation.fromJson(_recommendationJson());
      final rendered = formatMoney(
        item.recommendedPrice!,
        currency: item.currency,
        priceTick: item.priceTick,
        fractionDigits: item.priceTickScale,
      );
      expect(rendered, '1234.50 UAH');
      expect(item.recommendedPrice.toString(), '1234.567');
    });

    test('REGRESSION: USD не подменяется знаком гривны', () {
      final item = PricingRecommendation.fromJson(
        _recommendationJson(currency: 'USD'),
      );
      final rendered = formatMoney(
        item.recommendedPrice!,
        currency: item.currency,
        priceTick: item.priceTick,
        fractionDigits: item.priceTickScale,
      );
      expect(item.currency, 'USD');
      expect(rendered, '1234.50 USD');
      expect(rendered, isNot(contains('₴')));
    });

    test('REGRESSION: price_tick применяется к отображаемой цене', () {
      final item = PricingRecommendation.fromJson(_recommendationJson());
      expect(
        formatDecimalAmount(
          item.recommendedPrice!,
          priceTick: item.priceTick,
          fractionDigits: item.priceTickScale,
        ),
        '1234.50',
      );
    });

    testWidgets('REGRESSION: ручная цена отправляется в кратности tick', (
      tester,
    ) async {
      Map<String, dynamic>? decision;
      final item = PricingRecommendation.fromJson(_recommendationJson());
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Builder(
              builder: (context) => FilledButton(
                onPressed: () async {
                  decision = await showRecommendationDecisionDialog(
                    context,
                    recommendation: item,
                    decision: 'overridden',
                  );
                },
                child: const Text('Open'),
              ),
            ),
          ),
        ),
      );

      await tester.tap(find.text('Open'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField).first, '1234.76');
      await tester.tap(find.text('Записать'));
      await tester.pumpAndSettle();

      expect(decision?['new_price'], '1235.00');
    });
  });

  group('§4 вариация 26: reason-коды в UI', () {
    test('REGRESSION: LOW_DISPERSION и HIGH_DISPERSION различимы', () {
      expect(
        PricingRecommendation.reasonLabel('LOW_DISPERSION'),
        isNot(PricingRecommendation.reasonLabel('HIGH_DISPERSION')),
      );
      expect(
        PricingRecommendation.reasonLabel('LOW_DISPERSION'),
        'слишком низкий разброс цен',
      );
    });

    test('REGRESSION: неизвестный код не маскируется под перевод', () {
      expect(
        PricingRecommendation.reasonLabel('SOME_NEW_GATE_CODE'),
        'Неизвестная причина (SOME_NEW_GATE_CODE)',
      );
    });

    test('REGRESSION: reasonSummary показывает число скрытых причин', () {
      final item = PricingRecommendation.fromJson(
        _recommendationJson(
          reasonCodes: const [
            'LOW_CONFIDENCE',
            'LOW_COVERAGE',
            'LOW_MATCH',
            'LOW_TIER',
          ],
        ),
      );
      expect(item.reasonCodes.length, 4);
      expect(item.reasonSummary, endsWith('и ещё 2'));
    });
  });

  group('§4 вариация 25: переключение языка ru↔uk', () {
    testWidgets('AUDIT: карточка fitment остаётся русской при uk', (
      tester,
    ) async {
      final recommendation = FitmentMarketRecommendation.fromJson({
        'id': 'fr-1',
        'analysis_id': 'an-1',
        'action': 'consider_raise',
        'strategy': 'balanced',
        'current_price': '1000',
        'recommended_price': '1200',
        'currency': 'UAH',
        'confidence': '0.8',
        'reason_codes': <String>[],
        'warnings': <String>[],
      });
      await tester.pumpWidget(
        MaterialApp(
          locale: const Locale('uk'),
          supportedLocales: AppLanguage.values.map((item) => item.locale),
          localizationsDelegates: GlobalMaterialLocalizations.delegates,
          home: Scaffold(
            body: SingleChildScrollView(
              child: FitmentRecommendationCard(
                recommendation: recommendation,
                isSubmitting: false,
                onReview:
                    ({
                      required operation,
                      required reasonCode,
                      approvedPrice,
                      comment,
                      allowBelowFloor = false,
                      belowFloorWarningConfirmed = false,
                    }) async => true,
              ),
            ),
          ),
        ),
      );
      await tester.pump();
      // Русские подписи присутствуют, украинских нет.
      expect(find.text('Принять'), findsOneWidget);
      expect(find.text('Прийняти'), findsNothing);
      expect(find.text('Отклонить'), findsOneWidget);
      expect(find.text('Нужно исследование'), findsOneWidget);
      expect(find.text('Рассмотреть повышение'), findsOneWidget);
    });

    test('AUDIT: подписи моделей магазина не локализованы', () {
      final run = SyncRun.fromJson({
        'status': 'running',
        'progress_current': 3,
        'progress_total': 10,
        'error': null,
      });
      expect(run.statusLabel, 'выполняется');
      final store = StoreSummary.fromJson({
        'id': 's1',
        'external_id': '2847093',
        'name': null,
        'url': 'https://prom.ua/c2847093-kemp.html',
        'kind': 'owned',
        'product_count': 10,
        'last_synced_at': null,
      });
      expect(store.syncDescription, 'ещё не синхронизирован');
      expect(store.displayName, 'Prom store 2847093');
    });
  });

  group('Наличие товара', () {
    test('REGRESSION: неизвестное наличие не считается отсутствием', () {
      final product = StoreProduct.fromJson({
        'id': 'p1',
        'name': 'Item',
        'url': 'https://prom.ua/p1.html',
        'sku': 'A1',
        'brand': 'BOSCH',
        'current_price': null,
        'currency': 'UAH',
        'is_available': null,
        'image_url': null,
      });
      expect(product.isAvailable, isNull);
      expect(product.details, contains('Наличие не указано'));
      expect(product.details, isNot(contains('Нет в наличии')));
    });
  });

  group('§4 вариации 23-24: 375 pt и textScale 2.0', () {
    testWidgets('AUDIT: карточка fitment на 375 pt без переполнения', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(375, 812);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);
      final recommendation = FitmentMarketRecommendation.fromJson({
        'id': 'fr-1',
        'analysis_id': 'an-1',
        'action': 'consider_reduce',
        'strategy': 'balanced',
        'current_price': '123456.78',
        'recommended_price': '98765.43',
        'currency': 'UAH',
        'confidence': '0.8',
        'reason_codes': <String>[],
        'warnings': <String>[],
      });
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: FitmentRecommendationCard(
                recommendation: recommendation,
                isSubmitting: false,
                onReview:
                    ({
                      required operation,
                      required reasonCode,
                      approvedPrice,
                      comment,
                      allowBelowFloor = false,
                      belowFloorWarningConfirmed = false,
                    }) async => true,
              ),
            ),
          ),
        ),
      );
      await tester.pump();
      expect(tester.takeException(), isNull);
    });

    testWidgets('AUDIT: карточка fitment при textScale 2.0', (tester) async {
      tester.view.physicalSize = const Size(375, 812);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);
      final recommendation = FitmentMarketRecommendation.fromJson({
        'id': 'fr-1',
        'analysis_id': 'an-1',
        'action': 'manual_research_required',
        'strategy': 'balanced',
        'current_price': '1000',
        'recommended_price': null,
        'currency': 'UAH',
        'confidence': '0.4',
        'reason_codes': <String>[],
        'warnings': <String>['LOW_SAMPLE'],
      });
      await tester.pumpWidget(
        MaterialApp(
          home: MediaQuery(
            data: const MediaQueryData(textScaler: TextScaler.linear(2.0)),
            child: Scaffold(
              body: SingleChildScrollView(
                child: FitmentRecommendationCard(
                  recommendation: recommendation,
                  isSubmitting: false,
                  onReview:
                      ({
                        required operation,
                        required reasonCode,
                        approvedPrice,
                        comment,
                        allowBelowFloor = false,
                        belowFloorWarningConfirmed = false,
                      }) async => true,
                ),
              ),
            ),
          ),
        ),
      );
      await tester.pump();
      expect(tester.takeException(), isNull);
    });
  });

  group('Идемпотентность HITL-решений', () {
    test(
      'REGRESSION: два одинаковых review дают один idempotency_key',
      () async {
        final keys = <String>[];
        final api = FitmentApi(
          ApiClient(
            client: MockClient((request) async {
              keys.add(jsonDecode(request.body)['idempotency_key'] as String);
              return http.Response('{}', 200);
            }),
            baseUrl: 'http://api.test',
          ),
        );
        await api.reviewCandidate(
          'assessment-1',
          decision: 'mark_candidate_compatible',
          reasonCode: 'human_fitment_confirmed',
        );
        await api.reviewCandidate(
          'assessment-1',
          decision: 'mark_candidate_compatible',
          reasonCode: 'human_fitment_confirmed',
        );
        expect(keys.length, 2);
        expect(keys[0], keys[1]);
      },
    );
  });

  group('§4 вариация 19: 401/403 от API', () {
    test(
      'REGRESSION: 403 сохраняет machine code без Dart-map message',
      () async {
        final api = ApiClient(
          client: MockClient(
            (request) async => http.Response(
              jsonEncode({
                'detail': {
                  'code': 'INSUFFICIENT_WORKSPACE_ROLE',
                  'required_roles': ['owner', 'admin'],
                  'actual_role': 'member',
                },
              }),
              403,
            ),
          ),
          baseUrl: 'http://api.test',
        );
        Object? captured;
        try {
          await api.getJson('/api/v1/anything', authenticated: false);
        } catch (error) {
          captured = error;
        }
        expect(captured, isA<ApiException>());
        final failure = captured! as ApiException;
        expect(failure.statusCode, 403);
        expect(failure.code, 'INSUFFICIENT_WORKSPACE_ROLE');
        expect(failure.message, 'API returned HTTP 403');
        expect(failure.requiredRoles, ['owner', 'admin']);
        expect(failure.actualRole, 'member');
      },
    );

    test(
      'REGRESSION: 422 не превращает validation list в сырую строку',
      () async {
        final api = ApiClient(
          client: MockClient(
            (request) async => http.Response(
              jsonEncode({
                'detail': [
                  {
                    'type': 'missing',
                    'loc': ['body', 'oe'],
                    'msg': 'Field required',
                  },
                ],
              }),
              422,
            ),
          ),
          baseUrl: 'http://api.test',
        );
        Object? captured;
        try {
          await api.postJson('/api/v1/anything', authenticated: false);
        } catch (error) {
          captured = error;
        }
        final failure = captured! as ApiException;
        expect(failure.statusCode, 422);
        expect(failure.message, 'API validation failed');
        expect(failure.validationErrors, hasLength(1));
        expect(failure.validationErrors.single.type, 'missing');
        expect(failure.validationErrors.single.location, ['body', 'oe']);
        expect(failure.validationErrors.single.message, 'Field required');
      },
    );
  });

  group('§4 вариация V-48: быстрый повторный поиск', () {
    test('REGRESSION: устаревший ответ не заменяет более новый', () async {
      final slow = Completer<http.Response>();
      final fast = Completer<http.Response>();
      final client = MockClient((request) {
        final query = request.url.queryParameters['q'];
        if (query == 'slow') return slow.future;
        if (query == 'fast') return fast.future;
        return Future.value(_auditCatalogHttpResponse('initial'));
      });
      final container = ProviderContainer(
        overrides: [
          catalogApiProvider.overrideWithValue(
            CatalogApi(
              ApiClient(client: client, baseUrl: 'http://api.audit.test'),
            ),
          ),
        ],
      );
      addTearDown(container.dispose);
      final subscription = container.listen(
        catalogControllerProvider,
        (_, _) {},
      );
      addTearDown(subscription.close);
      await container.read(catalogControllerProvider.future);

      final slowSearch = container
          .read(catalogControllerProvider.notifier)
          .search('slow');
      await Future<void>.delayed(Duration.zero);
      final fastSearch = container
          .read(catalogControllerProvider.notifier)
          .search('fast');
      await Future<void>.delayed(Duration.zero);

      fast.complete(_auditCatalogHttpResponse('fast'));
      await fastSearch;
      slow.complete(_auditCatalogHttpResponse('slow'));
      await slowSearch;

      final state = container.read(catalogControllerProvider).requireValue;
      expect(state.query, 'fast');
      expect(state.page.items.single.name, 'fast');
    });
  });

  group('§4 вариация V-40: ошибка сети при loadMore', () {
    test('REGRESSION: уже загруженная страница сохраняется', () async {
      final client = MockClient((request) async {
        if (request.url.queryParameters['offset'] == '1') {
          return http.Response(
            jsonEncode({'detail': 'network unavailable'}),
            500,
            headers: const {'content-type': 'application/json; charset=utf-8'},
          );
        }
        return _auditCatalogHttpResponse('retained', total: 2);
      });
      final container = ProviderContainer(
        overrides: [
          catalogApiProvider.overrideWithValue(
            CatalogApi(
              ApiClient(client: client, baseUrl: 'http://api.audit.test'),
            ),
          ),
        ],
      );
      addTearDown(container.dispose);
      final subscription = container.listen(
        catalogControllerProvider,
        (_, _) {},
      );
      addTearDown(subscription.close);
      await container.read(catalogControllerProvider.future);

      await container.read(catalogControllerProvider.notifier).loadMore();

      final state = container.read(catalogControllerProvider).requireValue;
      expect(state.page.items.single.name, 'retained');
      expect(state.page.total, 2);
      expect(state.isLoadingMore, isFalse);
      expect(state.error, contains('network unavailable'));
    });
  });

  group('Аудит v2: доступность и покрывающая UI-матрица', () {
    testWidgets('REGRESSION: MarkoButton имеет цель нажатия не меньше 44 pt', (
      tester,
    ) async {
      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.light,
          home: Scaffold(
            body: MarkoButton(label: 'Подключить', onPressed: () {}),
          ),
        ),
      );

      final size = tester.getSize(find.byType(MarkoButton));
      // ignore: avoid_print
      print({
        'surface': 'MarkoButton',
        'width': size.width,
        'height': size.height,
      });
      expect(
        size.height,
        greaterThanOrEqualTo(44),
        reason: 'Интерактивная цель должна быть не меньше 44 pt.',
      );
    });

    for (final surface in _AuditP0Surface.values) {
      testWidgets('AUDIT MATRIX: ${surface.name} — 108 комбинаций '
          'state×width×scale×lang', (tester) async {
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.reset);

        var combinations = 0;
        final renderExceptions = <String>[];
        final forbiddenWithoutDedicatedCopy = <String>[];
        for (final state in _AuditUiState.values) {
          for (final width in const [375.0, 768.0, 1440.0]) {
            for (final scale in const [1.0, 1.3, 2.0]) {
              for (final locale in const [Locale('ru'), Locale('uk')]) {
                combinations += 1;
                tester.view.physicalSize = Size(width, 1100);
                await tester.pumpWidget(
                  _auditSurfaceApp(
                    surface: surface,
                    state: state,
                    locale: locale,
                    textScale: scale,
                  ),
                );
                await tester.pump();
                if (state != _AuditUiState.loading) {
                  // Several production surfaces contain intentionally
                  // repeating progress/cursor animations, so an unbounded
                  // pumpAndSettle cannot terminate. Two bounded frames still
                  // flush the provider future and the resulting layout.
                  await tester.pump(const Duration(milliseconds: 100));
                }
                final exception = tester.takeException();
                final key =
                    '${surface.name}/${state.name}/'
                    '${width.toInt()}/$scale/${locale.languageCode}';
                if (exception != null) {
                  renderExceptions.add('$key: $exception');
                }
                if (state == _AuditUiState.forbidden &&
                    find.textContaining('403').evaluate().isEmpty &&
                    find.textContaining('доступ').evaluate().isEmpty &&
                    find.textContaining('доступу').evaluate().isEmpty) {
                  final visibleText = tester
                      .widgetList<Text>(find.byType(Text))
                      .map(
                        (widget) =>
                            widget.data ??
                            widget.textSpan?.toPlainText() ??
                            '<empty>',
                      )
                      .take(8)
                      .join(' | ');
                  forbiddenWithoutDedicatedCopy.add('$key [$visibleText]');
                }
              }
            }
          }
        }

        // ignore: avoid_print
        print({
          'surface': surface.name,
          'combinations': combinations,
          'render_exceptions': renderExceptions,
          'forbidden_without_dedicated_copy': forbiddenWithoutDedicatedCopy,
        });
        expect(combinations, 108);
        expect(
          renderExceptions,
          isEmpty,
          reason: 'Каждая P0-комбинация должна отрисоваться без исключений.',
        );
        expect(
          forbiddenWithoutDedicatedCopy,
          isEmpty,
          reason: 'Forbidden должен иметь отдельное понятное состояние.',
        );
      });
    }

    for (final surface in _AuditSecondarySurface.values) {
      testWidgets('AUDIT PAIRWISE: ${surface.name} — 18 строк силы 2', (
        tester,
      ) async {
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.reset);
        final renderExceptions = <String>[];
        for (final row in _auditPairwiseRows) {
          tester.view.physicalSize = Size(row.width, 1100);
          await tester.pumpWidget(
            _auditSecondarySurfaceApp(surface: surface, row: row),
          );
          await tester.pump();
          if (row.state != _AuditUiState.loading) {
            await tester.pump(const Duration(milliseconds: 100));
          }
          final exception = tester.takeException();
          if (exception != null) {
            renderExceptions.add(
              '${surface.name}/${row.state.name}/'
              '${row.width.toInt()}/${row.scale}/'
              '${row.locale.languageCode}: $exception',
            );
          }
        }
        // ignore: avoid_print
        print({
          'surface': surface.name,
          'pairwise_rows': _auditPairwiseRows.length,
          'render_exceptions': renderExceptions,
          'uncovered_interaction_groups':
              '4 тройные группы факторов; взаимодействия силы >=3 не покрыты',
        });
        expect(_auditPairwiseRows.length, 18);
        expect(
          renderExceptions,
          isEmpty,
          reason:
              'Каждая pairwise-комбинация должна отрисоваться без исключений.',
        );
      });
    }

    testWidgets('REGRESSION: dashboard chrome выдерживает textScale 2.0', (
      tester,
    ) async {
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = const Size(1440, 1100);
      addTearDown(tester.view.reset);
      await tester.pumpWidget(
        _auditSecondarySurfaceApp(
          surface: _AuditSecondarySurface.dashboard,
          row: const (
            state: _AuditUiState.partial,
            width: 1440,
            scale: 2.0,
            locale: Locale('ru'),
          ),
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));
    });

    testWidgets(
      'REGRESSION: dashboard mobile chrome выдерживает textScale 2.0',
      (tester) async {
        tester.view.devicePixelRatio = 1;
        tester.view.physicalSize = const Size(375, 1100);
        addTearDown(tester.view.reset);
        await tester.pumpWidget(
          _auditSecondarySurfaceApp(
            surface: _AuditSecondarySurface.dashboard,
            row: const (
              state: _AuditUiState.success,
              width: 375,
              scale: 2.0,
              locale: Locale('ru'),
            ),
          ),
        );
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 100));
      },
    );
  });
}

enum _AuditP0Surface { catalog, recommendations, stores, productDetails }

enum _AuditUiState { loading, empty, partial, error, forbidden, success }

enum _AuditSecondarySurface {
  auth,
  dashboard,
  storeProducts,
  catalogContextDialog,
  recommendationDecisionDialog,
  tierOverrideDialog,
  fitmentCandidatesPanel,
}

typedef _AuditPairwiseRow = ({
  _AuditUiState state,
  double width,
  double scale,
  Locale locale,
});

const _auditPairwiseRows = <_AuditPairwiseRow>[
  (state: _AuditUiState.empty, width: 768, scale: 2.0, locale: Locale('uk')),
  (state: _AuditUiState.success, width: 768, scale: 1.3, locale: Locale('ru')),
  (state: _AuditUiState.partial, width: 1440, scale: 2.0, locale: Locale('ru')),
  (
    state: _AuditUiState.forbidden,
    width: 375,
    scale: 1.3,
    locale: Locale('uk'),
  ),
  (state: _AuditUiState.partial, width: 375, scale: 1.0, locale: Locale('uk')),
  (
    state: _AuditUiState.forbidden,
    width: 768,
    scale: 1.0,
    locale: Locale('ru'),
  ),
  (state: _AuditUiState.loading, width: 768, scale: 2.0, locale: Locale('ru')),
  (state: _AuditUiState.success, width: 1440, scale: 1.0, locale: Locale('uk')),
  (state: _AuditUiState.success, width: 375, scale: 2.0, locale: Locale('ru')),
  (state: _AuditUiState.loading, width: 1440, scale: 1.0, locale: Locale('ru')),
  (state: _AuditUiState.error, width: 768, scale: 1.0, locale: Locale('uk')),
  (state: _AuditUiState.partial, width: 768, scale: 1.3, locale: Locale('uk')),
  (state: _AuditUiState.empty, width: 1440, scale: 1.3, locale: Locale('ru')),
  (state: _AuditUiState.empty, width: 375, scale: 1.0, locale: Locale('ru')),
  (state: _AuditUiState.error, width: 375, scale: 1.3, locale: Locale('ru')),
  (
    state: _AuditUiState.forbidden,
    width: 1440,
    scale: 2.0,
    locale: Locale('ru'),
  ),
  (state: _AuditUiState.loading, width: 375, scale: 1.3, locale: Locale('uk')),
  (state: _AuditUiState.error, width: 1440, scale: 2.0, locale: Locale('uk')),
];

Widget _auditSurfaceApp({
  required _AuditP0Surface surface,
  required _AuditUiState state,
  required Locale locale,
  required double textScale,
}) {
  final auditKey = ValueKey(
    'audit-p0-${surface.name}-${state.name}-'
    '${locale.languageCode}-$textScale',
  );
  final child = switch (surface) {
    _AuditP0Surface.catalog => const CatalogPage(onOpenPriceComparison: _noop),
    _AuditP0Surface.recommendations => const RecommendationsPage(),
    _AuditP0Surface.stores => const StoresPage(ownedOnly: true),
    _AuditP0Surface.productDetails => CatalogProductDetailsSheet(
      product: _auditProduct,
      loadCompetitors: () => _auditComparisonFor(state),
      onOpenPricing: _noop,
    ),
  };
  final app = MaterialApp(
    theme: AppTheme.light,
    locale: locale,
    supportedLocales: const [Locale('ru'), Locale('uk')],
    localizationsDelegates: GlobalMaterialLocalizations.delegates,
    builder: (context, appChild) => MediaQuery(
      data: MediaQuery.of(
        context,
      ).copyWith(textScaler: TextScaler.linear(textScale)),
      child: appChild!,
    ),
    home: Scaffold(body: child),
  );
  return KeyedSubtree(
    key: auditKey,
    child: switch (surface) {
      _AuditP0Surface.catalog => ProviderScope(
        retry: (_, _) => null,
        overrides: [
          catalogControllerProvider.overrideWith(
            () => _AuditCatalogController(state),
          ),
        ],
        child: app,
      ),
      _AuditP0Surface.recommendations => ProviderScope(
        retry: (_, _) => null,
        overrides: [
          recommendationsControllerProvider.overrideWith(
            () => _AuditRecommendationsController(state),
          ),
        ],
        child: app,
      ),
      _AuditP0Surface.stores => ProviderScope(
        retry: (_, _) => null,
        overrides: [
          storesControllerProvider.overrideWith(
            () => _AuditStoresController(state),
          ),
        ],
        child: app,
      ),
      _AuditP0Surface.productDetails => app,
    },
  );
}

Widget _auditSecondarySurfaceApp({
  required _AuditSecondarySurface surface,
  required _AuditPairwiseRow row,
}) {
  final auditKey = ValueKey(
    'audit-secondary-${surface.name}-${row.state.name}-'
    '${row.width}-${row.scale}-${row.locale.languageCode}',
  );
  final child = switch (surface) {
    _AuditSecondarySurface.auth => const AuthPage(),
    _AuditSecondarySurface.dashboard => const DashboardPage(),
    _AuditSecondarySurface.storeProducts => const StoreProductsPage(
      storeId: 'store-audit',
    ),
    _AuditSecondarySurface.catalogContextDialog => _AuditDialogLauncher(
      open: (context) => showCatalogContextDialog(
        context,
        initialStatus: row.state == _AuditUiState.empty ? 'unknown' : 'stale',
        initialContext: row.state == _AuditUiState.empty
            ? const {}
            : const {
                'stock_qty': 30,
                'stock_age_days': 365,
                'expected_units_sold': 1,
              },
      ),
    ),
    _AuditSecondarySurface.recommendationDecisionDialog => _AuditDialogLauncher(
      open: (context) => showRecommendationDecisionDialog(
        context,
        recommendation: _auditRecommendation,
        decision: row.state == _AuditUiState.empty ? 'rejected' : 'overridden',
      ),
    ),
    _AuditSecondarySurface.tierOverrideDialog => _AuditDialogLauncher(
      open: (context) => showTierOverrideDialog(
        context,
        currentTier: row.state == _AuditUiState.empty
            ? 'unknown'
            : 'aftermarket',
      ),
    ),
    _AuditSecondarySurface.fitmentCandidatesPanel =>
      const SingleChildScrollView(
        child: FitmentCandidatesPanel(catalogItemId: 'item-audit'),
      ),
  };
  final app = MaterialApp(
    theme: AppTheme.light,
    locale: row.locale,
    supportedLocales: const [Locale('ru'), Locale('uk')],
    localizationsDelegates: GlobalMaterialLocalizations.delegates,
    builder: (context, appChild) => MediaQuery(
      data: MediaQuery.of(
        context,
      ).copyWith(textScaler: TextScaler.linear(row.scale)),
      child: appChild!,
    ),
    home: Scaffold(body: child),
  );
  return KeyedSubtree(
    key: auditKey,
    child: switch (surface) {
      _AuditSecondarySurface.auth => ProviderScope(
        retry: (_, _) => null,
        overrides: [
          authControllerProvider.overrideWith(
            () => _AuditAuthController(row.state),
          ),
        ],
        child: app,
      ),
      _AuditSecondarySurface.dashboard => ProviderScope(
        retry: (_, _) => null,
        overrides: [
          authControllerProvider.overrideWith(
            () => _AuditAuthController(_AuditUiState.success, signedIn: true),
          ),
          attentionControllerProvider.overrideWith(
            () => _AuditAttentionController(row.state),
          ),
          recommendationsControllerProvider.overrideWith(
            () => _AuditRecommendationsController(row.state),
          ),
          catalogControllerProvider.overrideWith(
            () => _AuditCatalogController(_AuditUiState.success),
          ),
          storesControllerProvider.overrideWith(
            () => _AuditStoresController(_AuditUiState.success),
          ),
          systemStatusProvider.overrideWith((ref) async => SystemHealth.active),
          appLanguageProvider.overrideWith(
            () => _AuditAppLanguageController(row.locale),
          ),
        ],
        child: app,
      ),
      _AuditSecondarySurface.storeProducts => ProviderScope(
        retry: (_, _) => null,
        overrides: [
          storeProductsProvider('store-audit').overrideWith(
            () => _AuditStoreProductsController('store-audit', row.state),
          ),
        ],
        child: app,
      ),
      _AuditSecondarySurface.fitmentCandidatesPanel => ProviderScope(
        retry: (_, _) => null,
        overrides: [
          fitmentControllerProvider('item-audit').overrideWith(
            () => _AuditFitmentController('item-audit', row.state),
          ),
        ],
        child: app,
      ),
      _AuditSecondarySurface.catalogContextDialog ||
      _AuditSecondarySurface.recommendationDecisionDialog ||
      _AuditSecondarySurface.tierOverrideDialog => app,
    },
  );
}

class _AuditDialogLauncher extends StatefulWidget {
  const _AuditDialogLauncher({required this.open});

  final Future<Object?> Function(BuildContext context) open;

  @override
  State<_AuditDialogLauncher> createState() => _AuditDialogLauncherState();
}

class _AuditDialogLauncherState extends State<_AuditDialogLauncher> {
  bool _opened = false;

  @override
  Widget build(BuildContext context) {
    if (!_opened) {
      _opened = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) widget.open(context);
      });
    }
    return const SizedBox.expand();
  }
}

class _AuditAppLanguageController extends AppLanguageController {
  _AuditAppLanguageController(this.locale);

  final Locale locale;

  @override
  AppLanguage build() =>
      locale.languageCode == 'uk' ? AppLanguage.ukrainian : AppLanguage.russian;
}

class _AuditAuthController extends AuthController {
  _AuditAuthController(this.auditState, {this.signedIn = false});

  final _AuditUiState auditState;
  final bool signedIn;

  @override
  Future<MarkoAuthState> build() async {
    switch (auditState) {
      case _AuditUiState.loading:
        return Completer<MarkoAuthState>().future;
      case _AuditUiState.error:
      case _AuditUiState.forbidden:
        return _auditFailure(auditState);
      case _AuditUiState.partial:
        return const MarkoAuthState(
          user: null,
          busy: false,
          error: 'Сессия загружена частично',
          notice: null,
        );
      case _AuditUiState.empty:
        return MarkoAuthState.initial;
      case _AuditUiState.success:
        return signedIn ? _auditSignedInAuthState : MarkoAuthState.initial;
    }
  }
}

class _AuditStoreProductsController extends StoreProductsController {
  _AuditStoreProductsController(super.storeId, this.auditState)
    : super(searchDebounce: Duration.zero);

  final _AuditUiState auditState;

  @override
  Future<StoreProductsState> build() async {
    switch (auditState) {
      case _AuditUiState.loading:
        return Completer<StoreProductsState>().future;
      case _AuditUiState.error:
      case _AuditUiState.forbidden:
        return _auditFailure(auditState);
      case _AuditUiState.empty:
        return StoreProductsState(
          store: _auditStore,
          page: ProductPage(items: [], total: 0),
        );
      case _AuditUiState.partial:
        return StoreProductsState(
          store: _auditStore,
          page: ProductPage(items: [_auditStoreProduct], total: 30),
          error: 'Получен 1 из 30 товаров',
        );
      case _AuditUiState.success:
        return StoreProductsState(
          store: _auditStore,
          page: ProductPage(items: [_auditStoreProduct], total: 1),
        );
    }
  }
}

class _AuditFitmentController extends FitmentController {
  _AuditFitmentController(super.catalogItemId, this.auditState);

  final _AuditUiState auditState;

  @override
  Future<FitmentReviewState> build() async {
    switch (auditState) {
      case _AuditUiState.loading:
        return Completer<FitmentReviewState>().future;
      case _AuditUiState.error:
      case _AuditUiState.forbidden:
        return _auditFailure(auditState);
      case _AuditUiState.empty:
        return const FitmentReviewState(bundle: _auditFitmentEmptyBundle);
      case _AuditUiState.partial:
        return const FitmentReviewState(
          bundle: _auditFitmentPartialBundle,
          error: 'Получено 1 из 30 evidence-групп',
        );
      case _AuditUiState.success:
        return const FitmentReviewState(bundle: _auditFitmentSuccessBundle);
    }
  }
}

void _noop() {}

Never _auditFailure(_AuditUiState state) {
  if (state == _AuditUiState.forbidden) {
    throw const ApiException(
      '{code: INSUFFICIENT_WORKSPACE_ROLE, actual_role: member}',
      statusCode: 403,
    );
  }
  throw const ApiException('network unavailable', statusCode: 500);
}

class _AuditCatalogController extends CatalogController {
  _AuditCatalogController(this.auditState);

  final _AuditUiState auditState;

  @override
  Future<CatalogState> build() async {
    switch (auditState) {
      case _AuditUiState.loading:
        return Completer<CatalogState>().future;
      case _AuditUiState.error:
      case _AuditUiState.forbidden:
        return _auditFailure(auditState);
      case _AuditUiState.empty:
        return const CatalogState(page: _auditCatalogEmpty);
      case _AuditUiState.partial:
        return CatalogState(
          page: CatalogProductPage(
            items: [_auditProduct],
            total: 30,
            catalogTotal: 30,
            listingTotal: 30,
            duplicatesRemoved: 0,
            storeTotal: 1,
            stores: [_auditStoreOption],
          ),
          error: 'Получено 1 из 30',
        );
      case _AuditUiState.success:
        return CatalogState(page: _auditCatalogSuccess);
    }
  }
}

class _AuditRecommendationsController extends RecommendationsController {
  _AuditRecommendationsController(this.auditState);

  final _AuditUiState auditState;

  @override
  Future<RecommendationsState> build() async {
    switch (auditState) {
      case _AuditUiState.loading:
        return Completer<RecommendationsState>().future;
      case _AuditUiState.error:
      case _AuditUiState.forbidden:
        return _auditFailure(auditState);
      case _AuditUiState.empty:
        return const RecommendationsState(
          page: RecommendationPage(items: [], total: 0, runId: null),
          queue: 'all',
          sort: 'ABSOLUTE_RECOMMENDED_CHANGE',
        );
      case _AuditUiState.partial:
        return RecommendationsState(
          page: RecommendationPage(
            items: [_auditRecommendation],
            total: 30,
            runId: 'run-audit',
          ),
          queue: 'all',
          sort: 'ABSOLUTE_RECOMMENDED_CHANGE',
          error: 'Получено 1 из 30',
        );
      case _AuditUiState.success:
        return RecommendationsState(
          page: RecommendationPage(
            items: [_auditRecommendation],
            total: 1,
            runId: 'run-audit',
          ),
          queue: 'all',
          sort: 'ABSOLUTE_RECOMMENDED_CHANGE',
        );
    }
  }
}

class _AuditAttentionController extends AttentionController {
  _AuditAttentionController(this.auditState);

  final _AuditUiState auditState;

  @override
  Future<AttentionState> build() async {
    switch (auditState) {
      case _AuditUiState.loading:
        return Completer<AttentionState>().future;
      case _AuditUiState.error:
      case _AuditUiState.forbidden:
        return _auditFailure(auditState);
      case _AuditUiState.empty:
        return const AttentionState(
          summary: _auditAttentionEmptySummary,
          page: AttentionPageResult(items: [], total: 0, limit: 50, offset: 0),
        );
      case _AuditUiState.partial:
        return AttentionState(
          summary: _auditAttentionSummary,
          page: AttentionPageResult(
            items: [_auditAttentionProduct],
            total: 30,
            limit: 50,
            offset: 0,
          ),
          error: 'Получена 1 из 30 оценок',
        );
      case _AuditUiState.success:
        return AttentionState(
          summary: _auditAttentionSummary,
          page: AttentionPageResult(
            items: [_auditAttentionProduct],
            total: 1,
            limit: 50,
            offset: 0,
          ),
        );
    }
  }
}

class _AuditStoresController extends StoresController {
  _AuditStoresController(this.auditState);

  final _AuditUiState auditState;

  @override
  Future<StoresState> build() async {
    switch (auditState) {
      case _AuditUiState.loading:
        return Completer<StoresState>().future;
      case _AuditUiState.error:
      case _AuditUiState.forbidden:
        return _auditFailure(auditState);
      case _AuditUiState.empty:
        return const StoresState();
      case _AuditUiState.partial:
        return const StoresState(
          stores: [_auditStore],
          error: 'Получен 1 магазин, синхронизация недоступна',
        );
      case _AuditUiState.success:
        return const StoresState(stores: [_auditStore]);
    }
  }
}

Future<CatalogCompetitorComparison> _auditComparisonFor(_AuditUiState state) {
  switch (state) {
    case _AuditUiState.loading:
      return Completer<CatalogCompetitorComparison>().future;
    case _AuditUiState.error:
    case _AuditUiState.forbidden:
      return Future<CatalogCompetitorComparison>.delayed(
        Duration.zero,
        () => throw state == _AuditUiState.forbidden
            ? const ApiException(
                '{code: INSUFFICIENT_WORKSPACE_ROLE, actual_role: member}',
                statusCode: 403,
              )
            : const ApiException('network unavailable', statusCode: 500),
      );
    case _AuditUiState.empty:
      return Future.value(_auditEmptyComparison);
    case _AuditUiState.partial:
      return Future.value(_auditPartialComparison);
    case _AuditUiState.success:
      return Future.value(_auditSuccessComparison);
  }
}

final PricingRecommendation _auditRecommendation =
    PricingRecommendation.fromJson(
      _recommendationJson(
        action: 'MANUAL_REVIEW',
        reasonCodes: const ['LOW_COVERAGE'],
      ),
    );

const _auditAttentionEmptySummary = AttentionSummary(
  total: 0,
  overpriced: 0,
  underpriced: 0,
  inMarket: 0,
  reviewRequired: 0,
  noData: 0,
  processing: 0,
  updatedAt: null,
);

final _auditAttentionSummary = AttentionSummary(
  total: 1,
  overpriced: 1,
  underpriced: 0,
  inMarket: 0,
  reviewRequired: 0,
  noData: 0,
  processing: 0,
  updatedAt: DateTime.utc(2026, 7, 29),
);

final _auditAttentionProduct = AttentionProduct(
  productId: 'attention-audit',
  recommendationId: 'rec-1',
  name:
      'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX',
  sku: 'AUDIT-001',
  oe: '7E5827505A',
  brand: 'KEMP',
  sourceKind: 'PROM_STORE',
  sourceId: 'store-audit',
  status: 'OVERPRICED',
  severity: 20,
  ourPrice: '1800',
  marketLow: '1400',
  marketHigh: '1500',
  suggestedPrice: '1450',
  currency: 'UAH',
  differencePercent: '24.1',
  confidence: '0.8',
  evidenceCount: 5,
  reasonCodes: const ['MARKET_PRICE_LOWER'],
  marketCheckedAt: DateTime.utc(2026, 7, 29),
  updatedAt: DateTime.utc(2026, 7, 29),
);

const _auditStoreOption = CatalogStoreOption(
  storeId: 'store-audit',
  externalId: '2847093',
  name: 'KEMP',
);

const _auditStore = StoreSummary(
  id: 'store-audit',
  externalId: '2847093',
  name: 'KEMP',
  url: 'https://prom.ua/ua/c2847093-kemp.html',
  kind: 'owned',
  productCount: 30,
  lastSyncedAt: null,
);

const _auditSignedInAuthState = MarkoAuthState(
  user: AuthUser(
    id: 'user-audit',
    email: 'owner@example.test',
    displayName: 'Owner',
    avatarUrl: null,
    workspaceId: 'workspace-audit',
    workspaceRole: 'owner',
  ),
  busy: false,
  error: null,
  notice: null,
);

final _auditStoreProduct = StoreProduct(
  id: 'listing-audit',
  name:
      'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX',
  url: 'https://prom.ua/ua/p-audit.html',
  sku: '7E5827505A',
  brand: 'KEMP',
  price: 1800,
  currency: 'UAH',
  isAvailable: true,
  imageUrl: null,
);

const _auditFitmentEmptyBundle = FitmentReviewBundle(
  page: FitmentCandidatePage(items: [], total: 0, analysisId: null),
  recommendation: null,
);

const _auditFitmentPartialBundle = FitmentReviewBundle(
  page: FitmentCandidatePage(
    items: [],
    total: 30,
    analysisId: 'analysis-audit',
  ),
  recommendation: null,
);

const _auditFitmentSuccessBundle = FitmentReviewBundle(
  page: FitmentCandidatePage(items: [], total: 0, analysisId: 'analysis-audit'),
  recommendation: null,
);

http.Response _auditCatalogHttpResponse(String name, {int total = 1}) {
  return http.Response(
    jsonEncode({
      'items': [
        {
          'id': 'catalog-$name',
          'identity_kind': 'oe',
          'name': name,
          'sku': 'SKU-$name',
          'oe': 'OE-$name',
          'model_id': null,
          'brand': 'KEMP',
          'image_url': null,
          'price_min': '100.00',
          'price_max': '100.00',
          'currency': 'UAH',
          'listing_count': 1,
          'stores': <Object>[],
          'recommended_price': null,
          'recommendation_currency': null,
          'recommendation_action': null,
          'recommendation_computed_at': null,
        },
      ],
      'total': total,
      'catalog_total': total,
      'listing_total': total,
      'duplicates_removed': 0,
      'store_total': 0,
      'stores': <Object>[],
    }),
    200,
    headers: const {'content-type': 'application/json; charset=utf-8'},
  );
}

final _auditProduct = CatalogProduct(
  id: 'product-audit',
  identityKind: 'oe',
  name:
      'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX',
  sku: 'AUDIT-001',
  oe: '7E5827505A',
  modelId: null,
  brand: 'KEMP',
  imageUrl: null,
  priceMin: 1800,
  priceMax: 1800,
  currency: 'UAH',
  listingCount: 1,
  stores: [
    CatalogStorePresence(
      storeId: 'store-audit',
      externalId: '2847093',
      name: 'KEMP',
      url: 'https://prom.ua/ua/c2847093-kemp.html',
      listingUrl: 'https://prom.ua/ua/p-audit.html',
      listingCount: 1,
      price: 1800,
      currency: 'UAH',
      isAvailable: true,
    ),
  ],
);

const _auditCatalogEmpty = CatalogProductPage(
  items: [],
  total: 0,
  catalogTotal: 0,
  listingTotal: 0,
  duplicatesRemoved: 0,
  storeTotal: 0,
  stores: [],
);

final _auditCatalogSuccess = CatalogProductPage(
  items: [_auditProduct],
  total: 1,
  catalogTotal: 1,
  listingTotal: 1,
  duplicatesRemoved: 0,
  storeTotal: 1,
  stores: [_auditStoreOption],
);

final _auditOffer = CatalogCompetitorOffer(
  observationId: 'observation-audit',
  sellerId: 'seller-audit',
  sellerName: 'Конкурент',
  title: 'Замок крышки багажника 7E5827505A',
  url: 'https://prom.ua/ua/p-audit-competitor.html',
  price: 400,
  currency: 'UAH',
  isAvailable: true,
  normalizedPrice: 400,
  tier: 'aftermarket',
  matchConfidence: 0.95,
  observedAt: DateTime.utc(2026, 7, 29),
);

final _auditEmptyComparison = CatalogCompetitorComparison(
  recommendationId: null,
  comparedAt: null,
  currentPrice: 1800,
  fairPrice: null,
  recommendedPrice: null,
  currency: 'UAH',
  reasonCodes: [],
  items: [],
);

final _auditPartialComparison = CatalogCompetitorComparison(
  recommendationId: null,
  comparedAt: null,
  currentPrice: 1800,
  fairPrice: null,
  recommendedPrice: null,
  currency: 'UAH',
  reasonCodes: ['PARTIAL_EVIDENCE'],
  items: [_auditOffer],
);

final _auditSuccessComparison = CatalogCompetitorComparison(
  recommendationId: 'recommendation-audit',
  comparedAt: null,
  currentPrice: 1800,
  fairPrice: 400,
  recommendedPrice: 420,
  currency: 'UAH',
  reasonCodes: [],
  items: [_auditOffer],
);
