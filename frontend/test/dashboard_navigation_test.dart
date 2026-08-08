import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/core/app_language.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/core/system_status.dart';
import 'package:marko_client/features/auth/auth_controller.dart';
import 'package:marko_client/features/auth/auth_models.dart';
import 'package:marko_client/features/attention/attention_controller.dart';
import 'package:marko_client/features/attention/attention_models.dart';
import 'package:marko_client/features/catalog/catalog_controller.dart';
import 'package:marko_client/features/catalog/catalog_models.dart';
import 'package:marko_client/features/dashboard/dashboard_page.dart';
import 'package:marko_client/features/pricing/pricing_controller.dart';
import 'package:marko_client/features/pricing/pricing_api.dart';
import 'package:marko_client/features/pricing/pricing_models.dart';
import 'package:marko_client/features/stores/store_models.dart';
import 'package:marko_client/features/stores/stores_controller.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('desktop navigation follows the three-step daily workflow', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(_testApp());

    expect(find.text('Требует внимания'), findsWidgets);
    expect(find.text('Товары'), findsOneWidget);
    expect(find.text('Источники'), findsOneWidget);
    expect(find.text('Сравнение цен'), findsNothing);
    expect(find.text('Обзор'), findsNothing);

    await tester.tap(find.text('Источники'));
    await tester.pumpAndSettle();

    expect(find.text('Источники'), findsWidgets);
    expect(find.text('Подключённые'), findsOneWidget);
    expect(find.text('Kemp'), findsOneWidget);
    expect(find.text('Market competitor'), findsNothing);
    expect(find.byTooltip('Удалить магазин'), findsOneWidget);

    await tester.tap(find.byTooltip('Удалить магазин'));
    await tester.pumpAndSettle();
    expect(find.text('Удалить магазин?'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('confirm-delete-store')));
    await tester.pumpAndSettle();
    expect(find.text('Kemp'), findsNothing);
    expect(find.text('Магазинов пока нет'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('three destinations fit in the mobile navigation', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final semantics = tester.ensureSemantics();

    await tester.pumpWidget(_testApp());

    expect(find.text('Требует внимания'), findsOneWidget);
    expect(find.text('Товары'), findsOneWidget);
    expect(find.text('Источники'), findsOneWidget);
    expect(find.text('Обзор'), findsNothing);
    expect(find.bySemanticsLabel(RegExp(r'Выбрать язык')), findsOneWidget);

    await tester.tap(find.text('Источники'));
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
    semantics.dispose();
  });

  testWidgets('tabs switch one IndexedStack without pushing routes', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(_testApp(routeNavigation: true));

    IndexedStack stack() => tester.widget<IndexedStack>(
      find.byKey(const ValueKey('dashboard-indexed-stack')),
    );

    expect(stack().index, 0);
    await tester.tap(find.text('Товары'));
    await tester.pumpAndSettle();
    expect(stack().index, 1);

    await tester.tap(find.text('Источники'));
    await tester.pumpAndSettle();
    expect(stack().index, 2);
    expect(tester.takeException(), isNull);
  });

  testWidgets('deleting a store refreshes mounted catalog and attention tabs', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    _catalogBuilds = 0;
    _attentionBuilds = 0;

    await tester.pumpWidget(
      _testApp(
        attentionControllerBuilder: _CountingAttentionController.new,
        catalogControllerBuilder: _CountingCatalogController.new,
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('Товары'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Источники'));
    await tester.pumpAndSettle();

    expect(_attentionBuilds, 1);
    expect(_catalogBuilds, 1);
    await tester.tap(find.byTooltip('Удалить магазин'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const ValueKey('confirm-delete-store')));
    await tester.pumpAndSettle();

    expect(_attentionBuilds, 2);
    expect(_catalogBuilds, 2);
    expect(tester.takeException(), isNull);
  });

  testWidgets('product details return to the attention workflow', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(_testApp());

    await tester.tap(find.text('Товары'));
    await tester.pumpAndSettle();
    expect(find.text('Товары'), findsWidgets);
    expect(tester.takeException(), isNull);

    await tester.tap(find.byTooltip('Показать конкурентов'));
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey('catalog-product-details-sheet')),
      findsOneWidget,
    );
    expect(find.text('Товары'), findsWidgets);
    expect(find.text('Auto Partner'), findsOneWidget);
    expect(find.text('Kemp'), findsNothing);

    await tester.tap(find.byKey(const ValueKey('catalog-details-compare')));
    await tester.pumpAndSettle();

    expect(find.text('Требует внимания'), findsWidgets);
    expect(find.text('Цены под контролем'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('catalog deep link restores its tab and opens the product', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      _testApp(initialCatalogProductId: 'catalog-product'),
    );
    await tester.pumpAndSettle();

    expect(find.text('Товары'), findsWidgets);
    expect(
      find.byKey(const ValueKey('catalog-product-details-sheet')),
      findsOneWidget,
    );
    expect(find.text('KEMP test product'), findsWidgets);
    expect(tester.takeException(), isNull);
  });

  testWidgets('recommendation deep link restores and expands its card', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 1000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      _testApp(
        initialRecommendationId: 'rec-deep',
        recommendationsControllerBuilder:
            _DeepLinkRecommendationsController.new,
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Deep-link brake pad'), findsOneWidget);
    expect(find.text('Проверить replay'), findsOneWidget);
    expect(find.text('Контекст склада'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('tapping a connected store opens the catalog filtered to it', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(_testApp());

    await tester.tap(find.text('Источники'));
    await tester.pumpAndSettle();
    expect(find.text('Подключённые'), findsOneWidget);

    await tester.tap(find.text('Kemp'));
    await tester.pumpAndSettle();

    // The catalog tab is open and its store filter carries that one store.
    expect(find.text('Товары'), findsWidgets);
    expect(find.text('Подключённые'), findsNothing);
    expect(
      find.textContaining('Kemp', findRichText: true),
      findsOneWidget,
      reason: 'the store filter chip names the store that was tapped',
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('catalog state survives switching IndexedStack tabs', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(_testApp());
    await tester.tap(find.text('Источники'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Kemp'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Kemp', findRichText: true), findsOneWidget);

    await tester.tap(find.text('Требует внимания'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Товары'));
    await tester.pumpAndSettle();

    expect(find.text('Товары'), findsWidgets);
    expect(find.textContaining('Kemp', findRichText: true), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('language selector sits above account and switches RU to UA', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(_testApp());
    await tester.pumpAndSettle();

    final selector = find.byKey(const ValueKey('language-selector'));
    expect(selector, findsOneWidget);
    expect(find.text('Русский'), findsOneWidget);
    expect(
      tester.getBottomLeft(selector).dy,
      lessThan(tester.getTopLeft(find.text('owner@example.test')).dy),
    );

    await tester.tap(selector);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Українська'));
    await tester.pumpAndSettle();

    expect(find.text('Потребує уваги'), findsWidgets);
    expect(find.text('Товари'), findsOneWidget);
    expect(find.text('Джерела'), findsOneWidget);
    expect(find.text('РОБОЧА ОБЛАСТЬ'), findsOneWidget);
    expect(find.text('owner@example.test'), findsOneWidget);
    expect(find.text('Українська'), findsOneWidget);
    expect(find.text('Ціни під контролем'), findsOneWidget);

    await tester.tap(find.text('Товари'));
    await tester.pumpAndSettle();
    expect(
      find.text('Пошук за OEM/OE, артикулу або назві оголошення'),
      findsOneWidget,
    );

    await tester.tap(find.text('Джерела'));
    await tester.pumpAndSettle();
    expect(find.text('Підключені'), findsOneWidget);
    expect(find.byTooltip('Видалити магазин'), findsOneWidget);

    await tester.tap(find.text('Потребує уваги'));
    await tester.pumpAndSettle();
    expect(find.text('Ціни під контролем'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}

Widget _testApp({
  StoresController Function()? storesControllerBuilder,
  AttentionController Function()? attentionControllerBuilder,
  CatalogController Function()? catalogControllerBuilder,
  RecommendationsController Function()? recommendationsControllerBuilder,
  String? initialCatalogProductId,
  String? initialRecommendationId,
  bool routeNavigation = false,
}) {
  return ProviderScope(
    overrides: [
      authControllerProvider.overrideWith(_TestAuthController.new),
      attentionControllerProvider.overrideWith(
        attentionControllerBuilder ?? _TestAttentionController.new,
      ),
      recommendationsControllerProvider.overrideWith(
        recommendationsControllerBuilder ?? _TestRecommendationsController.new,
      ),
      pricingApiProvider.overrideWithValue(_DeepLinkPricingApi()),
      catalogControllerProvider.overrideWith(
        catalogControllerBuilder ?? _TestCatalogController.new,
      ),
      storesControllerProvider.overrideWith(
        storesControllerBuilder ?? _TestStoresController.new,
      ),
      systemStatusProvider.overrideWith((ref) async => SystemHealth.active),
    ],
    child: Consumer(
      builder: (context, ref, _) {
        final language = ref.watch(appLanguageProvider);
        return MaterialApp(
          theme: AppTheme.light,
          locale: language.locale,
          supportedLocales: const [Locale('ru'), Locale('uk')],
          localizationsDelegates: GlobalMaterialLocalizations.delegates,
          home: DashboardPage(
            initialCatalogProductId: initialCatalogProductId,
            initialRecommendationId: initialRecommendationId,
            routeNavigation: routeNavigation,
          ),
        );
      },
    ),
  );
}

class _TestAuthController extends AuthController {
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

class _TestRecommendationsController extends RecommendationsController {
  @override
  Future<RecommendationsState> build() async {
    return const RecommendationsState(
      page: RecommendationPage(items: [], total: 0, runId: null),
      queue: 'all',
      sort: 'ABSOLUTE_RECOMMENDED_CHANGE',
    );
  }
}

class _TestAttentionController extends AttentionController {
  @override
  Future<AttentionState> build() async => const AttentionState(
    summary: AttentionSummary(
      total: 0,
      overpriced: 0,
      underpriced: 0,
      inMarket: 0,
      reviewRequired: 0,
      noData: 0,
      processing: 0,
      updatedAt: null,
    ),
    page: AttentionPageResult(items: [], total: 0, limit: 50, offset: 0),
  );
}

int _attentionBuilds = 0;

class _CountingAttentionController extends _TestAttentionController {
  @override
  Future<AttentionState> build() {
    _attentionBuilds += 1;
    return super.build();
  }
}

class _DeepLinkRecommendationsController extends RecommendationsController {
  @override
  Future<RecommendationsState> build() async {
    return RecommendationsState(
      page: RecommendationPage(
        items: [_deepLinkRecommendation()],
        total: 1,
        runId: 'run-1',
      ),
      queue: 'all',
      sort: 'ABSOLUTE_RECOMMENDED_CHANGE',
    );
  }
}

class _DeepLinkPricingApi extends PricingApi {
  _DeepLinkPricingApi()
    : super(
        ApiClient(
          client: MockClient((_) async => throw UnimplementedError()),
          baseUrl: 'http://api.test',
        ),
      );

  @override
  Future<List<RecommendationEvidence>> getEvidence(
    String recommendationId,
  ) async => const [];

  @override
  Future<List<PricingRunSummary>> listRuns({int limit = 25}) async => const [];
}

PricingRecommendation _deepLinkRecommendation() {
  return PricingRecommendation.fromJson({
    'id': 'rec-deep',
    'pricing_run_id': 'run-1',
    'catalog_snapshot_id': 'snapshot-1',
    'catalog_item_id': 'item-1',
    'sku': 'SKU-1',
    'oe_norm': 'OE1',
    'name': 'Deep-link brake pad',
    'category': 'brake_pads',
    'stock_status': 'fresh',
    'action': 'RAISE',
    'current_price': '100',
    'recommended_price': '120',
    'confidence': '0.9',
    'confidence_grade': 'A',
    'competitor_count': 4,
    'priority_score': '20',
    'priority_score_type': 'gross_uplift_opportunity',
    'reason_codes': <String>[],
    'currency': 'UAH',
    'price_tick': '1',
    'computed_at': '2026-07-30T12:00:00Z',
  });
}

class _TestCatalogController extends CatalogController {
  @override
  Future<CatalogState> build() async {
    return CatalogState(
      page: CatalogProductPage(
        items: [
          CatalogProduct(
            id: 'catalog-product',
            identityKind: 'brand_sku',
            name: 'KEMP test product',
            sku: '0331402053',
            oe: null,
            modelId: null,
            brand: 'KEMP',
            imageUrl: null,
            priceMin: 450,
            priceMax: 450,
            currency: 'UAH',
            listingCount: 1,
            stores: [
              CatalogStorePresence(
                storeId: 'owned-store',
                externalId: '2847093',
                name: 'Kemp',
                url: 'https://prom.ua/ua/c2847093-kemp.html',
                listingUrl: 'https://prom.ua/ua/p-kemp-product.html',
                listingCount: 1,
                price: 450,
                currency: 'UAH',
                isAvailable: true,
              ),
            ],
          ),
        ],
        total: 1,
        catalogTotal: 1,
        listingTotal: 1,
        duplicatesRemoved: 0,
        storeTotal: 1,
        stores: [
          CatalogStoreOption(
            storeId: 'owned-store',
            externalId: '2847093',
            name: 'Kemp',
          ),
        ],
      ),
    );
  }

  @override
  Future<void> selectStores(Set<String> storeIds) async {
    state = AsyncData(state.requireValue.copyWith(selectedStoreIds: storeIds));
  }

  @override
  Future<CatalogCompetitorComparison> loadCompetitors(
    CatalogProduct product,
  ) async {
    return CatalogCompetitorComparison(
      recommendationId: 'recommendation-id',
      comparedAt: DateTime.utc(2026, 7, 25, 13),
      currentPrice: 450,
      fairPrice: 440,
      recommendedPrice: 445,
      currency: 'UAH',
      reasonCodes: const [],
      items: [
        CatalogCompetitorOffer(
          observationId: 'competitor-observation',
          sellerId: 'auto-partner',
          sellerName: 'Auto Partner',
          title: 'Конкурентное объявление',
          url: 'https://prom.ua/ua/p-competitor.html',
          price: 440,
          currency: 'UAH',
          isAvailable: true,
          normalizedPrice: 440,
          tier: 'aftermarket_a',
          matchConfidence: 0.95,
          observedAt: DateTime.utc(2026, 7, 25, 12),
        ),
      ],
    );
  }
}

int _catalogBuilds = 0;

class _CountingCatalogController extends _TestCatalogController {
  @override
  Future<CatalogState> build() {
    _catalogBuilds += 1;
    return super.build();
  }
}

class _TestStoresController extends StoresController {
  @override
  Future<StoresState> build() async {
    return const StoresState(
      stores: [
        StoreSummary(
          id: 'owned-store',
          externalId: '1',
          name: 'Kemp',
          url: 'https://kemp.prom.ua',
          kind: 'owned',
          productCount: 12,
          lastSyncedAt: null,
        ),
        StoreSummary(
          id: 'competitor-store',
          externalId: '2',
          name: 'Market competitor',
          url: 'https://competitor.prom.ua',
          kind: 'competitor',
          productCount: 8,
          lastSyncedAt: null,
        ),
      ],
    );
  }

  @override
  Future<bool> deleteStore(StoreSummary store) async {
    final current = state.requireValue;
    state = AsyncData(
      current.copyWith(
        stores: current.stores
            .where((item) => item.id != store.id)
            .toList(growable: false),
      ),
    );
    return true;
  }
}
