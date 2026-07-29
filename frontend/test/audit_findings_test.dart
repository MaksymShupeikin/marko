// Аудит 2026-07-27: доказательства UI-находок (§4 вариации 17-26).
//
// Файл создан агентом-аудитором согласно CONSTRAINT_6(a).
// После remediation тесты фиксируют исправленное поведение Wave 0.

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/core/app_language.dart';
import 'package:marko_client/core/presentation_formatters.dart';
import 'package:marko_client/features/fitment/fitment_api.dart';
import 'package:marko_client/features/fitment/fitment_models.dart';
import 'package:marko_client/features/fitment/fitment_recommendation_card.dart';
import 'package:marko_client/features/pricing/pricing_models.dart';
import 'package:marko_client/features/pricing/recommendation_decision_dialog.dart';
import 'package:marko_client/features/stores/store_models.dart';

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
      expect(item.recommendedPrice, 1234.567);
      expect(item.priceTick, 0.5);
      expect(item.currency, 'UAH');
      expect(item.fairPrice, isNull);
    });

    test('AUDIT: отсутствие reason_codes роняет парсер (TypeError)', () {
      final json = _recommendationJson()..remove('reason_codes');
      expect(() => PricingRecommendation.fromJson(json), throwsA(isA<Error>()));
    });

    test('AUDIT: отсутствие competitor_count роняет парсер', () {
      final json = _recommendationJson()..remove('competitor_count');
      expect(() => PricingRecommendation.fromJson(json), throwsA(isA<Error>()));
    });
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

    test(
      'AUDIT: неизвестный код показывается как сырой enum в нижнем регистре',
      () {
        expect(
          PricingRecommendation.reasonLabel('SOME_NEW_GATE_CODE'),
          'some new gate code',
        );
      },
    );

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
    test('AUDIT: 403 отдаётся как обычное ApiException без различия', () async {
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
      // ФАКТ: структурированный код схлопывается в toString() Dart-мапы.
      expect(failure.message, startsWith('{code: INSUFFICIENT_WORKSPACE_ROLE'));
    });

    test('AUDIT: 422 от FastAPI показывается как сырой список', () async {
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
      expect(failure.message, startsWith('[{type: missing'));
    });
  });
}
