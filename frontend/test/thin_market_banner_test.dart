import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/products/products_models.dart';
import 'package:marko_client/features/products/widgets/product_details_panel.dart';

// Контракт C2/B8: менше трьох підтверджених цін — точну рекомендацію
// не показуємо, замість суми — чесний банер тонкого ринку.
void main() {
  const product = StoreProduct(
    id: 'product-1',
    name: 'Фільтр',
    url: 'https://kemp.prom.ua/p1.html',
    sku: 'F-1',
    brand: 'Kemp',
    price: 1100,
    currency: 'UAH',
    isAvailable: true,
    imageUrl: null,
  );

  CompetitorPriceReport report({required bool thinMarket}) {
    return CompetitorPriceReport(
      cached: false,
      observedAt: null,
      stats: CompetitorPriceStats(
        offersTotal: 2,
        sourcesTotal: 1,
        minPrice: 500,
        medianPrice: 510,
        maxPrice: 520,
        recommendedPrice: thinMarket ? null : 470,
        thinMarket: thinMarket,
      ),
      sources: const [
        SourcePriceResult(
          source: 'prom',
          label: 'Prom',
          status: 'ok',
          offersTotal: 2,
          offers: [
            MarketPriceOffer(
              source: 'prom',
              title: 'Пропозиція A',
              price: 500,
              currency: 'UAH',
              url: 'https://example.com/a',
              seller: 'Конкурент',
            ),
            MarketPriceOffer(
              source: 'prom',
              title: 'Пропозиція B',
              price: 520,
              currency: 'UAH',
              url: 'https://example.com/b',
              seller: 'Конкурент',
            ),
          ],
        ),
      ],
    );
  }

  Future<void> pump(WidgetTester tester, CompetitorPriceReport data) async {
    tester.view.physicalSize = const Size(700, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(() {
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: Scaffold(
          body: SingleChildScrollView(
            child: CompetitorPricesReport(report: data, product: product),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets('тонкий ринок показує банер замість рекомендованої суми', (
    tester,
  ) async {
    await pump(tester, report(thinMarket: true));

    expect(find.text('Ринок тонкий'), findsOneWidget);
    expect(
      find.textContaining('точну рекомендацію не даємо'),
      findsOneWidget,
    );
    expect(find.text('Рекомендована ціна'), findsNothing);
  });

  testWidgets('звичайний ринок показує рекомендацію, банера немає', (
    tester,
  ) async {
    await pump(tester, report(thinMarket: false));

    expect(find.text('Рекомендована ціна'), findsOneWidget);
    expect(find.text('Ринок тонкий'), findsNothing);
  });
}
