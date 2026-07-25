import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/catalog/catalog_controller.dart';
import 'package:marko_client/features/catalog/catalog_models.dart';
import 'package:marko_client/features/catalog/catalog_page.dart';
import 'package:marko_client/features/catalog/widgets/catalog_product_card.dart';

void main() {
  testWidgets('catalog shows deduplicated products and connected stores', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1000, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(_testApp());
    await tester.pumpAndSettle();

    expect(
      find.text('Поиск по OEM/OE, артикулу или названию объявления'),
      findsOneWidget,
    );
    expect(find.text('Загрузить XLSX'), findsNothing);
    expect(find.text('История импортов'), findsNothing);
    expect(find.text('parts-avto'), findsNothing);
    expect(find.text('kemp'), findsNothing);
    expect(find.text('Можно поднять до'), findsOneWidget);
    expect(find.text('700.00 UAH'), findsOneWidget);
    expect(find.text('Сейчас: 450.00 UAH'), findsOneWidget);
    expect(find.text('420.00–450.00 UAH'), findsNothing);
    expect(find.text('3 объявления объединены'), findsOneWidget);
    expect(find.text('OE/OEM'), findsOneWidget);
    expect(find.text('6 1131 36 9611'), findsOneWidget);
    final recommendedPrice = tester.widget<Text>(
      find.byKey(const ValueKey('catalog-recommended-price-product-id')),
    );
    expect(recommendedPrice.style?.color, MarkoTheme.light.positive);
    expect(find.byKey(const ValueKey('catalog-store-filter')), findsOneWidget);
    expect(
      tester
          .getSize(
            find.byKey(const ValueKey('catalog-product-card-product-id')),
          )
          .width,
      780,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('store counter opens catalog store filter', (tester) async {
    await tester.pumpWidget(_testApp());
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const ValueKey('catalog-store-filter')));
    await tester.pumpAndSettle();

    expect(find.text('Все магазины'), findsOneWidget);
    expect(find.text('Parts Avto'), findsOneWidget);
    expect(find.textContaining('ПРОФПАРТС'), findsOneWidget);

    await tester.tap(find.text('ПРОФПАРТС'));
    await tester.pumpAndSettle();

    expect(find.textContaining('ПРОФПАРТС'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('catalog remains usable on a mobile viewport', (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(_testApp());
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('catalog-oe-search')), findsOneWidget);
    expect(find.text('700.00 UAH'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('arrow opens an animated competitor panel before comparison', (
    tester,
  ) async {
    var comparisons = 0;

    await tester.pumpWidget(
      _testApp(onOpenPriceComparison: () => comparisons += 1),
    );
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey('catalog-product-details-sheet')),
      findsNothing,
    );
    await tester.tap(find.byTooltip('Показать конкурентов'));
    await tester.pump();

    final sheet = find.byKey(const ValueKey('catalog-product-details-sheet'));
    expect(sheet, findsOneWidget);
    final startX = tester.getTopLeft(sheet).dx;

    await tester.pump(const Duration(milliseconds: 140));
    final middleX = tester.getTopLeft(sheet).dx;
    expect(middleX, lessThan(startX));

    await tester.pumpAndSettle();
    final endX = tester.getTopLeft(sheet).dx;
    expect(endX, lessThan(middleX));
    expect(find.text('Конкурентные объявления'), findsOneWidget);
    expect(find.text('Реле стартера Bosch для Mercedes'), findsOneWidget);
    expect(find.text('Auto Partner'), findsOneWidget);
    expect(find.text('690.00 UAH'), findsOneWidget);
    expect(find.text('Учитывается в сравнении'), findsOneWidget);
    expect(find.text('KEMP Автозапчастини'), findsNothing);
    expect(find.text('Parts Avto'), findsNothing);
    expect(find.text('Основной'), findsNothing);
    expect(find.text('OE/OEM: 6 1131 36 9611'), findsOneWidget);
    expect(comparisons, 0);

    await tester.tap(find.byKey(const ValueKey('catalog-details-compare')));
    await tester.pumpAndSettle();

    expect(comparisons, 1);
    expect(sheet, findsNothing);
  });

  testWidgets('regular card tap opens the KEMP listing first', (tester) async {
    String? openedUrl;
    var detailOpens = 0;

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: Scaffold(
          body: SizedBox(
            width: 780,
            child: CatalogProductCard(
              product: _product,
              onShowDetails: () => detailOpens += 1,
              onOpenListing: (url) => openedUrl = url,
            ),
          ),
        ),
      ),
    );

    await tester.tap(
      find.byKey(const ValueKey('catalog-product-card-product-id')),
    );
    await tester.pump();

    expect(openedUrl, 'https://prom.ua/ua/p-kemp-product.html');
    expect(detailOpens, 0);

    openedUrl = null;
    await tester.tap(find.byTooltip('Показать конкурентов'));
    await tester.pump();

    expect(openedUrl, isNull);
    expect(detailOpens, 1);
  });

  testWidgets('catalog copy and listing panel switch to Ukrainian', (
    tester,
  ) async {
    await tester.pumpWidget(_testApp(locale: const Locale('uk')));
    await tester.pumpAndSettle();

    expect(
      find.text('Пошук за OEM/OE, артикулу або назві оголошення'),
      findsOneWidget,
    );
    expect(find.text('Товари'), findsOneWidget);

    await tester.tap(find.byTooltip('Показати конкурентів'));
    await tester.pumpAndSettle();

    expect(find.text('Конкурентні оголошення'), findsOneWidget);
    expect(find.text('Враховується у порівнянні'), findsOneWidget);
    expect(find.text('Перейти до порівняння цін'), findsOneWidget);
  });

  testWidgets('panel never substitutes owned stores for missing competitors', (
    tester,
  ) async {
    await tester.pumpWidget(_testApp(comparison: _emptyComparison));
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('Показать конкурентов'));
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey('catalog-competitors-empty')),
      findsOneWidget,
    );
    expect(
      find.text(
        'Для этого товара конкурентные объявления ещё не собраны. '
        'Запустите сравнение цен.',
      ),
      findsOneWidget,
    );
    expect(find.text('KEMP Автозапчастини'), findsNothing);
    expect(find.text('Parts Avto'), findsNothing);
  });
}

Widget _testApp({
  VoidCallback? onOpenPriceComparison,
  Locale locale = const Locale('ru'),
  CatalogCompetitorComparison? comparison,
}) {
  return ProviderScope(
    overrides: [
      catalogControllerProvider.overrideWith(
        () => _TestCatalogController(comparison ?? _comparison),
      ),
    ],
    child: MaterialApp(
      theme: AppTheme.light,
      locale: locale,
      supportedLocales: const [Locale('ru'), Locale('uk')],
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
      home: Scaffold(
        body: CatalogPage(
          onOpenPriceComparison: onOpenPriceComparison ?? () {},
        ),
      ),
    ),
  );
}

class _TestCatalogController extends CatalogController {
  _TestCatalogController(this.comparison);

  final CatalogCompetitorComparison comparison;

  @override
  Future<CatalogState> build() async => const CatalogState(page: _page);

  @override
  Future<CatalogCompetitorComparison> loadCompetitors(
    CatalogProduct product,
  ) async => comparison;

  @override
  Future<void> selectStore(String? storeId) async {
    final current = state.requireValue;
    state = AsyncData(
      current.copyWith(
        selectedStoreId: storeId,
        clearSelectedStore: storeId == null,
      ),
    );
  }
}

final _comparison = CatalogCompetitorComparison(
  recommendationId: 'recommendation-id',
  comparedAt: DateTime.utc(2026, 7, 25, 13),
  currentPrice: 450,
  fairPrice: 700,
  recommendedPrice: 700,
  currency: 'UAH',
  reasonCodes: const [],
  items: [
    CatalogCompetitorOffer(
      observationId: 'competitor-observation',
      sellerId: 'auto-partner',
      sellerName: 'Auto Partner',
      title: 'Реле стартера Bosch для Mercedes',
      url: 'https://prom.ua/ua/p-competitor.html',
      price: 690,
      currency: 'UAH',
      isAvailable: true,
      normalizedPrice: 705,
      tier: 'aftermarket_a',
      matchConfidence: 0.96,
      observedAt: DateTime.utc(2026, 7, 25, 12),
    ),
  ],
);

const _emptyComparison = CatalogCompetitorComparison(
  recommendationId: null,
  comparedAt: null,
  currentPrice: null,
  fairPrice: null,
  recommendedPrice: null,
  currency: null,
  reasonCodes: [],
  items: [],
);

const _page = CatalogProductPage(
  items: [_product],
  total: 1,
  catalogTotal: 1,
  listingTotal: 3,
  duplicatesRemoved: 2,
  storeTotal: 2,
  stores: [
    CatalogStoreOption(
      storeId: 'store-a',
      externalId: '3912822',
      name: 'Parts Avto',
    ),
    CatalogStoreOption(
      storeId: 'store-b',
      externalId: '3325174',
      name: 'ПРОФПАРТС',
    ),
  ],
);

const _product = CatalogProduct(
  id: 'product-id',
  identityKind: 'brand_sku',
  name: 'Втягивающее реле стартера Mercedes',
  sku: '0331402053',
  oe: '6 1131 36 9611',
  modelId: null,
  brand: 'KEMP',
  imageUrl: null,
  priceMin: 420,
  priceMax: 450,
  currency: 'UAH',
  listingCount: 3,
  recommendedPrice: 700,
  recommendationCurrency: 'UAH',
  recommendationAction: 'RAISE',
  recommendationComputedAt: null,
  stores: [
    CatalogStorePresence(
      storeId: 'store-a',
      externalId: '3912822',
      name: 'Parts Avto',
      url: 'https://prom.ua/ua/c3912822-parts-avto.html',
      listingUrl: 'https://prom.ua/ua/p1-product.html',
      listingCount: 2,
      price: 420,
      currency: 'UAH',
      isAvailable: true,
    ),
    CatalogStorePresence(
      storeId: 'store-b',
      externalId: '2847093',
      name: 'KEMP Автозапчастини',
      url: 'https://prom.ua/ua/c2847093-kemp.html',
      listingUrl: 'https://prom.ua/ua/p-kemp-product.html',
      listingCount: 1,
      price: 450,
      currency: 'UAH',
      isAvailable: true,
    ),
  ],
);
