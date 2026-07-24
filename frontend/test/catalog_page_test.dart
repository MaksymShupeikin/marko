import 'package:flutter/material.dart';
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

    expect(find.text('Поиск по OE/OEM'), findsOneWidget);
    expect(find.text('Загрузить XLSX'), findsNothing);
    expect(find.text('История импортов'), findsNothing);
    expect(find.text('parts-avto'), findsNothing);
    expect(find.text('kemp'), findsNothing);
    expect(find.text('450.00 UAH'), findsOneWidget);
    expect(find.text('420.00–450.00 UAH'), findsNothing);
    expect(find.text('3 объявления объединены'), findsOneWidget);
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

  testWidgets('catalog remains usable on a mobile viewport', (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(_testApp());
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('catalog-oe-search')), findsOneWidget);
    expect(find.text('450.00 UAH'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('comparison button triggers a separate catalog action', (
    tester,
  ) async {
    var comparisons = 0;

    await tester.pumpWidget(
      _testApp(onOpenPriceComparison: () => comparisons += 1),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byTooltip('Сравнить цены'));
    await tester.pump();

    expect(comparisons, 1);
  });

  testWidgets('regular card tap opens the KEMP listing first', (tester) async {
    String? openedUrl;
    var comparisons = 0;

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: Scaffold(
          body: SizedBox(
            width: 780,
            child: CatalogProductCard(
              product: _product,
              onCompare: () => comparisons += 1,
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
    expect(comparisons, 0);

    openedUrl = null;
    await tester.tap(find.byTooltip('Сравнить цены'));
    await tester.pump();

    expect(openedUrl, isNull);
    expect(comparisons, 1);
  });
}

Widget _testApp({VoidCallback? onOpenPriceComparison}) {
  return ProviderScope(
    overrides: [
      catalogControllerProvider.overrideWith(_TestCatalogController.new),
    ],
    child: MaterialApp(
      theme: AppTheme.light,
      home: Scaffold(
        body: CatalogPage(
          onOpenPriceComparison: onOpenPriceComparison ?? () {},
        ),
      ),
    ),
  );
}

class _TestCatalogController extends CatalogController {
  @override
  Future<CatalogState> build() async => const CatalogState(page: _page);
}

const _page = CatalogProductPage(
  items: [_product],
  total: 1,
  catalogTotal: 1,
  listingTotal: 3,
  duplicatesRemoved: 2,
  storeTotal: 2,
);

const _product = CatalogProduct(
  id: 'product-id',
  identityKind: 'brand_sku',
  name: 'Втягивающее реле стартера Mercedes',
  sku: '0331402053',
  oe: null,
  modelId: null,
  brand: 'KEMP',
  imageUrl: null,
  priceMin: 420,
  priceMax: 450,
  currency: 'UAH',
  listingCount: 3,
  stores: [
    CatalogStorePresence(
      storeId: 'store-a',
      externalId: '3912822',
      name: 'parts-avto',
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
      name: 'kemp',
      url: 'https://prom.ua/ua/c2847093-kemp.html',
      listingUrl: 'https://prom.ua/ua/p-kemp-product.html',
      listingCount: 1,
      price: 450,
      currency: 'UAH',
      isAvailable: true,
    ),
  ],
);
