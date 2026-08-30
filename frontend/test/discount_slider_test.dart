import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/products/products_models.dart';
import 'package:marko_client/features/products/widgets/product_details_panel.dart';

void main() {
  testWidgets('повзунок знижки миттєво перераховує позицію на ринку', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(700, 1100);
    tester.view.devicePixelRatio = 1;
    addTearDown(() {
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });

    final report = CompetitorPriceReport(
      cached: false,
      observedAt: null,
      stats: const CompetitorPriceStats(
        offersTotal: 1,
        sourcesTotal: 1,
        minPrice: 1000,
        medianPrice: 1000,
        maxPrice: 1000,
      ),
      sources: const [
        SourcePriceResult(
          source: 'prom',
          label: 'Prom',
          status: 'ok',
          offersTotal: 1,
          offers: [
            MarketPriceOffer(
              source: 'prom',
              title: 'Пропозиція конкурента',
              price: 1000,
              currency: 'UAH',
              url: 'https://example.com/offer',
              seller: 'Конкурент',
            ),
          ],
        ),
      ],
    );
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

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: Scaffold(
          body: SingleChildScrollView(
            child: CompetitorPricesReport(report: report, product: product),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    // 1100 проти медіани 1000 — дорожче ринку.
    expect(find.text('Дорожче за медіану ринку'), findsOneWidget);
    expect(find.textContaining('Рухайте повзунок'), findsOneWidget);

    // Тягнемо повзунок до максимуму: 1100 × 0.70 = 770 < 1000.
    await tester.drag(find.byType(Slider), const Offset(600, 0));
    await tester.pumpAndSettle();

    expect(find.text('Найкраща ціна на ринку'), findsOneWidget);
    expect(find.textContaining('770'), findsOneWidget);
  });
}
