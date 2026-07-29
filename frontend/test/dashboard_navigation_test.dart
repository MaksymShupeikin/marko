import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/app_language.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/core/system_status.dart';
import 'package:marko_client/features/auth/auth_controller.dart';
import 'package:marko_client/features/auth/auth_models.dart';
import 'package:marko_client/features/catalog/catalog_controller.dart';
import 'package:marko_client/features/catalog/catalog_models.dart';
import 'package:marko_client/features/dashboard/dashboard_page.dart';
import 'package:marko_client/features/pricing/pricing_controller.dart';
import 'package:marko_client/features/pricing/pricing_models.dart';
import 'package:marko_client/features/stores/store_models.dart';
import 'package:marko_client/features/stores/stores_controller.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('only Мои магазины remains as the desktop store destination', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(_testApp());

    expect(find.text('Сравнение цен'), findsWidgets);
    expect(find.text('Магазины'), findsNothing);
    expect(find.text('Мои магазины'), findsOneWidget);

    await tester.tap(find.text('Мои магазины'));
    await tester.pumpAndSettle();

    expect(find.text('Мои магазины'), findsNWidgets(3));
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

  testWidgets('four destinations fit in the mobile navigation', (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(_testApp());

    expect(find.text('Магазины'), findsNothing);
    expect(find.text('Мои магазины'), findsOneWidget);
    expect(find.text('Обзор'), findsOneWidget);

    await tester.tap(find.text('Мои магазины'));
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
  });

  testWidgets('catalog arrow opens details panel, then price comparison', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(_testApp());

    await tester.tap(find.text('Каталог'));
    await tester.pumpAndSettle();
    expect(find.text('Каталог Prom.ua'), findsOneWidget);
    expect(tester.takeException(), isNull);

    await tester.tap(find.byTooltip('Показать конкурентов'));
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey('catalog-product-details-sheet')),
      findsOneWidget,
    );
    expect(find.text('Каталог Prom.ua'), findsOneWidget);
    expect(find.text('Auto Partner'), findsOneWidget);
    expect(find.text('Kemp'), findsNothing);

    await tester.tap(find.byKey(const ValueKey('catalog-details-compare')));
    await tester.pumpAndSettle();

    expect(find.text('Сравнение цен'), findsNWidgets(3));
    expect(find.text('Каталог Prom.ua'), findsNothing);
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

    expect(find.text('Порівняння цін'), findsWidgets);
    expect(find.text('Мої магазини'), findsOneWidget);
    expect(find.text('Огляд'), findsOneWidget);
    expect(find.text('РОБОЧА ОБЛАСТЬ'), findsOneWidget);
    expect(find.text('owner@example.test'), findsOneWidget);
    expect(find.text('Українська'), findsOneWidget);
    expect(find.text('Рекомендацій поки немає'), findsOneWidget);

    await tester.tap(find.text('Каталог'));
    await tester.pumpAndSettle();
    expect(
      find.text('Пошук за OEM/OE, артикулу або назві оголошення'),
      findsOneWidget,
    );

    await tester.tap(find.text('Мої магазини'));
    await tester.pumpAndSettle();
    expect(find.text('Підключені'), findsOneWidget);
    expect(find.byTooltip('Видалити магазин'), findsOneWidget);

    await tester.tap(find.text('Огляд'));
    await tester.pumpAndSettle();
    expect(find.text('Ціни під контролем'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}

Widget _testApp() {
  return ProviderScope(
    overrides: [
      authControllerProvider.overrideWith(_TestAuthController.new),
      recommendationsControllerProvider.overrideWith(
        _TestRecommendationsController.new,
      ),
      catalogControllerProvider.overrideWith(_TestCatalogController.new),
      storesControllerProvider.overrideWith(_TestStoresController.new),
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
          home: const DashboardPage(),
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

class _TestCatalogController extends CatalogController {
  @override
  Future<CatalogState> build() async {
    return const CatalogState(
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
