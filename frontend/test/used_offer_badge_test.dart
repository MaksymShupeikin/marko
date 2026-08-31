import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/products/products_models.dart';
import 'package:marko_client/features/products/widgets/product_details_panel.dart';

// Б/в-пропозиція видима, але не ринок: червоний бейдж пояснює це сам,
// ціна сіра, а чип різниці «-… ₴» не лякає заказчика цифрою, яка
// не бере участі в розрахунку.
void main() {
  const product = StoreProduct(
    id: 'product-1',
    name: 'Амортизатор',
    url: 'https://kemp.prom.ua/p1.html',
    sku: 'A-1',
    brand: 'Kemp',
    price: 1100,
    currency: 'UAH',
    isAvailable: true,
    imageUrl: null,
  );

  final report = CompetitorPriceReport(
    cached: false,
    observedAt: null,
    stats: const CompetitorPriceStats(
      offersTotal: 2,
      sourcesTotal: 1,
      minPrice: 500,
      medianPrice: 700,
      maxPrice: 900,
      recommendedPrice: 470,
      thinMarket: false,
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
            title: 'Амортизатор з розборки',
            price: 900,
            currency: 'UAH',
            url: 'https://example.com/used',
            seller: 'Авторозбірка',
            condition: 'used',
          ),
          MarketPriceOffer(
            source: 'prom',
            title: 'Амортизатор новий',
            price: 500,
            currency: 'UAH',
            url: 'https://example.com/new',
            seller: 'Конкурент',
            condition: 'new',
          ),
        ],
      ),
    ],
  );

  Future<void> pump(WidgetTester tester) async {
    tester.view.physicalSize = const Size(700, 1600);
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
            child: CompetitorPricesReport(report: report, product: product),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  // Ціна в картці пропозиції — єдиний Text з кеглем 14: цінова драбина
  // й банери малюють свої цифри іншими стилями.
  Text offerCardPrice(WidgetTester tester, String text) {
    return tester
        .widgetList<Text>(find.text(text))
        .firstWhere((t) => t.style?.fontSize == 14);
  }

  testWidgets('б/в: червоний бейдж, сіра ціна, без чипа різниці', (
    tester,
  ) async {
    await pump(tester);
    final colors = MarkoTheme.of(
      tester.element(find.byType(CompetitorPricesReport)),
    );

    expect(find.text('б/в — не в ціні'), findsOneWidget);
    expect(offerCardPrice(tester, '900 ₴').style?.color, colors.muted);
    // Різниця 1100-900=200 не показується: цієї ціни нема в розрахунку.
    expect(find.text('-200 ₴'), findsNothing);
  });

  testWidgets('нова деталь виглядає як раніше: тихий бейдж, чорна ціна, різниця є', (
    tester,
  ) async {
    await pump(tester);
    final colors = MarkoTheme.of(
      tester.element(find.byType(CompetitorPricesReport)),
    );

    expect(find.text('нове'), findsOneWidget);
    expect(offerCardPrice(tester, '500 ₴').style?.color, colors.ink);
    expect(find.text('-600 ₴'), findsOneWidget);
  });
}
