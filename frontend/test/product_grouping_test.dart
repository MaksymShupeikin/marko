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
      eligibleOffersTotal: 2,
      sourcesTotal: 1,
      minPrice: 1100,
      medianPrice: 1150,
      maxPrice: 1200,
      recommendedPriceFrom: 1023,
      recommendedPrice: 1034,
      recommendedPriceTo: 1045,
      pricingStatus: 'reliable',
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
    expect(
      find.text('Магазин KEMP: можна підвищити на 84 грн до 1 034 грн'),
      findsOneWidget,
    );
    expect(
      find.text(
        'Магазин Avtobust: рекомендовано знизити на 166 грн до 1 034 грн',
      ),
      findsOneWidget,
    );
    expect(find.text('Магазин Profparts: ціна не вказана'), findsOneWidget);
  });

  testWidgets('discount slider is local, starts at 6 and calculates 1/30%', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(700, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: const Scaffold(
          body: SingleChildScrollView(
            child: SizedBox(
              width: 500,
              child: CompetitorPricesReport(report: report, product: product),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    var slider = tester.widget<Slider>(
      find.byKey(const ValueKey('pricing-discount-slider')),
    );
    expect(slider.min, 1);
    expect(slider.max, 30);
    expect(slider.divisions, 29);
    expect(slider.value, 6);
    expect(find.text('1 034 ₴'), findsWidgets);

    slider.onChanged!(1);
    await tester.pump();
    expect(find.text('1%'), findsOneWidget);
    expect(
      tester
          .widget<Text>(find.byKey(const ValueKey('pricing-slider-target')))
          .data,
      '1 089 ₴',
    );

    slider = tester.widget<Slider>(
      find.byKey(const ValueKey('pricing-discount-slider')),
    );
    slider.onChanged!(30);
    await tester.pump();
    expect(find.text('30%'), findsOneWidget);
    expect(
      tester
          .widget<Text>(find.byKey(const ValueKey('pricing-slider-target')))
          .data,
      '770 ₴',
    );
    expect(
      find.text('Магазин KEMP: рекомендовано знизити на 180 грн до 770 грн'),
      findsOneWidget,
    );
  });

  testWidgets('one verified market offer does not produce a recommendation', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(700, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);

    const insufficientReport = CompetitorPriceReport(
      cached: false,
      observedAt: null,
      stats: CompetitorPriceStats(
        offersTotal: 1,
        eligibleOffersTotal: 1,
        sourcesTotal: 1,
        minPrice: 2082,
        medianPrice: 2082,
        maxPrice: 2082,
        pricingStatus: 'insufficient',
      ),
      sources: [
        SourcePriceResult(
          source: 'prom',
          label: 'Prom.ua',
          status: 'ok',
          offersTotal: 1,
          offers: [
            MarketPriceOffer(
              source: 'prom',
              title: 'Кут бампера VW T4',
              price: 2082,
              currency: 'UAH',
              url: 'https://prom.ua/offer',
              condition: 'new',
              verified: true,
            ),
          ],
        ),
      ],
    );

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: const Scaffold(
          body: SizedBox(
            width: 500,
            height: 1300,
            child: ProductDetailsPreview(
              product: product,
              report: insufficientReport,
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Недостатньо даних для рекомендації'), findsOneWidget);
    expect(find.text('Рекомендована ціна'), findsNothing);
    expect(find.text('Найкраща ціна на ринку'), findsNothing);
    expect(find.byType(Slider), findsNothing);
  });

  testWidgets('conflict hides recommendation and slider', (tester) async {
    const conflictReport = CompetitorPriceReport(
      cached: false,
      observedAt: null,
      stats: CompetitorPriceStats(
        offersTotal: 2,
        eligibleOffersTotal: 0,
        sourcesTotal: 1,
        pricingStatus: 'conflict',
      ),
      sources: [],
    );

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: const Scaffold(
          body: CompetitorPricesReport(report: conflictReport),
        ),
      ),
    );

    expect(
      find.text('Суперечливі ціни — рекомендацію зупинено'),
      findsOneWidget,
    );
    expect(find.byType(Slider), findsNothing);
    expect(find.textContaining('Рекомендована ціна'), findsNothing);
  });
}
