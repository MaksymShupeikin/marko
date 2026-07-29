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
    expect(find.text('ПРОФПАРТС'), findsOneWidget);

    await tester.tap(find.text('ПРОФПАРТС'));
    await tester.pumpAndSettle();

    // Multi-select keeps the menu open so more than one store can be picked.
    expect(find.textContaining('ПРОФПАРТС'), findsNWidgets(2));

    await tester.tap(find.text('Готово'));
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
    expect(
      find.text('Сопоставление с объявлениями конкурентов'),
      findsOneWidget,
    );
    expect(find.text('Перейти к сравнению цен'), findsNothing);
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
    expect(find.text('Зіставлення з оголошеннями конкурентів'), findsOneWidget);
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

  testWidgets(
    'discovery button shows parsed candidates without pricing claim',
    (tester) async {
      await tester.pumpWidget(_testApp(comparison: _emptyComparison));
      await tester.pumpAndSettle();

      await tester.tap(find.byTooltip('Показать конкурентов'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('catalog-details-discover')));
      await tester.pumpAndSettle();

      expect(
        find.byKey(const ValueKey('catalog-discovery-section')),
        findsOneWidget,
      );
      expect(find.text('Найдено парсером'), findsOneWidget);
      expect(find.text('Замок багажника 7E5827505A'), findsOneWidget);
      expect(find.text('629.00 UAH'), findsOneWidget);
      expect(
        find.byKey(const ValueKey('catalog-pricing-evidence-block')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('catalog-reference-only-block')),
        findsOneWidget,
      );
      expect(
        find.text('Показаны справочно · в расчёт не входят · 1'),
        findsOneWidget,
      );
      // Once as the listing badge, once as the histogram row.
      expect(
        find.text('Справочно · уровень бренда не определён'),
        findsNWidgets(2),
      );
      expect(
        find.byKey(const ValueKey('catalog-discovery-histogram')),
        findsOneWidget,
      );
      expect(
        find.byKey(const ValueKey('catalog-discovery-coverage')),
        findsOneWidget,
      );
      expect(
        find.textContaining('достигнут защитный предел 10 страниц'),
        findsOneWidget,
      );
      expect(find.text('Учитывается в сравнении'), findsNothing);
    },
  );
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
          canAdministerWorkspace: true,
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
  Future<CatalogCompetitorComparison> discoverCompetitors(
    CatalogProduct product,
  ) async => _discoveryComparison;

  @override
  Future<void> selectStores(Set<String> storeIds) async {
    final current = state.requireValue;
    state = AsyncData(current.copyWith(selectedStoreIds: storeIds));
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

final _discoveryComparison = CatalogCompetitorComparison(
  recommendationId: null,
  comparedAt: null,
  currentPrice: null,
  fairPrice: null,
  recommendedPrice: null,
  currency: null,
  reasonCodes: const [],
  items: const [],
  discoveryRunId: 'discovery-run',
  discoveredAt: DateTime.utc(2026, 7, 25, 14),
  discoveryQuery: '7E5827505A',
  discoveryStatus: 'completed',
  promReportedTotal: 91,
  discoveredTotal: 1,
  discoveryRetrievedCount: 29,
  discoveryPersistedCount: 29,
  pricingEvidenceCount: 0,
  referenceOnlyCount: 1,
  rejectedCandidateCount: 28,
  selectionHistogram: const {
    'REJECTED:DISMANTLER_SELLER': 2,
    'REJECTED:OEM_NOT_FOUND': 1,
    'REFERENCE_ONLY:TIER_UNKNOWN': 26,
  },
  searchPagesFetched: 10,
  searchPageLimit: 10,
  unfetchedCount: 62,
  coverageRatio: 29 / 91,
  coverageReason: 'SEARCH_PAGE_HARD_CAP',
  selectionMethodVersion: 'deterministic-candidate-gates-v1',
  selectionConfigSha256: 'aaaaaaaa',
  brandRulesDatasetId: 'NO_BRAND_DICTIONARY_CONFIGURED',
  discoveryItems: const [
    CatalogDiscoveredOffer(
      discoveryOfferId: 'discovery-offer',
      sourceListingId: '1402874053',
      sellerId: '668922',
      sellerName: 'Autoparts IF',
      title: 'Замок багажника 7E5827505A',
      url: 'https://prom.ua/ua/p1402874053-item.html',
      sku: 'DF-11260',
      brand: 'Detali IF',
      salePrice: 629,
      referencePrice: null,
      currency: 'UAH',
      measureUnit: 'шт.',
      isAvailable: true,
      titleContainsQuery: true,
      identityStatus: 'QUERY_TOKEN_PRESENT',
      sourceConfidence: 1,
      reasonCodes: ['DISCOVERY_ONLY_NOT_PRICING_EVIDENCE'],
      selectionStatus: 'REFERENCE_ONLY',
      selectionReason: 'TIER_UNKNOWN',
      passedGates: [
        'own_seller',
        'dismantler_seller',
        'condition',
        'remanufactured',
        'oem_identity',
        'oem_stuffing',
        'variant',
        'package',
        'applicability',
      ],
      selectionFlags: [],
      selectionDetails: {'stopped_gate': 'tier_known'},
      predictedTier: 'unknown',
      tierConfidence: 0,
    ),
  ],
  referenceOnly: const [
    CatalogDiscoveredOffer(
      discoveryOfferId: 'discovery-offer',
      sourceListingId: '1402874053',
      sellerId: '668922',
      sellerName: 'Autoparts IF',
      title: 'Замок багажника 7E5827505A',
      url: 'https://prom.ua/ua/p1402874053-item.html',
      sku: 'DF-11260',
      brand: 'Detali IF',
      salePrice: 629,
      referencePrice: null,
      currency: 'UAH',
      measureUnit: 'шт.',
      isAvailable: true,
      titleContainsQuery: true,
      identityStatus: 'QUERY_TOKEN_PRESENT',
      sourceConfidence: 1,
      reasonCodes: ['DISCOVERY_ONLY_NOT_PRICING_EVIDENCE'],
      selectionStatus: 'REFERENCE_ONLY',
      selectionReason: 'TIER_UNKNOWN',
      passedGates: [
        'own_seller',
        'dismantler_seller',
        'condition',
        'remanufactured',
        'oem_identity',
        'oem_stuffing',
        'variant',
        'package',
        'applicability',
        'tier_classification',
        'own_brand',
      ],
      selectionFlags: [],
      selectionDetails: {'stopped_gate': 'tier_known'},
      predictedTier: 'unknown',
      tierConfidence: 0,
    ),
  ],
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
