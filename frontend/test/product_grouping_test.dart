import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/products/products_models.dart';
import 'package:marko_client/features/products/widgets/product_details_panel.dart';

void main() {
  const product = StoreProduct(
    id: 'product-1',
    name: 'Grouped product',
    url: 'https://prom.ua/product-1',
    sku: 'SKU-1',
    brand: 'Brand',
    price: 950,
    currency: 'UAH',
    isAvailable: true,
    imageUrl: null,
    storeId: 'store-1',
    storeName: 'KEMP',
    groupSize: 3,
    siblings: [
      SiblingListing(
        listingId: 'product-2',
        storeId: 'store-2',
        storeName: 'Avtobust',
        price: 1200,
        currency: 'UAH',
        isAvailable: true,
        url: 'https://prom.ua/product-2',
      ),
      SiblingListing(
        listingId: 'product-3',
        storeId: 'store-3',
        storeName: 'Profparts',
        price: null,
        currency: 'UAH',
        isAvailable: null,
        url: 'https://prom.ua/product-3',
      ),
    ],
  );

  const report = CompetitorPriceReport(
    cached: false,
    observedAt: null,
    stats: CompetitorPriceStats(
      offersTotal: 1,
      sourcesTotal: 1,
      minPrice: 1100,
      medianPrice: 1150,
      maxPrice: 1200,
      recommendedPrice: 1089,
    ),
    sources: [],
  );

  testWidgets('details show every own copy and per-store market guidance', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(700, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: const Scaffold(
          body: SizedBox(
            width: 500,
            height: 1300,
            child: ProductDetailsPreview(product: product, report: report),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('KEMP · 950 ₴ · представник'), findsOneWidget);
    expect(find.text('Avtobust · 1 200 ₴'), findsOneWidget);
    expect(find.text('Profparts · ціна не вказана'), findsOneWidget);

    await tester.scrollUntilVisible(
      find.text('Рекомендації для своїх магазинів'),
      300,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('Рекомендації для своїх магазинів'), findsOneWidget);
    expect(find.text('Магазин KEMP: 950 грн — в межах ринку'), findsOneWidget);
    expect(
      find.text(
        'Магазин Avtobust: 1 200 грн — вище ринку, рекомендовано ≤ 1 089 грн',
      ),
      findsOneWidget,
    );
    expect(find.text('Магазин Profparts: ціна не вказана'), findsOneWidget);
  });
}
