import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/products/products_models.dart';
import 'package:marko_client/features/products/widgets/product_details_panel.dart';

void main() {
  CompetitorPriceReport report({required String source, String? city}) {
    return CompetitorPriceReport(
      cached: false,
      observedAt: null,
      stats: const CompetitorPriceStats(
        offersTotal: 1,
        sourcesTotal: 1,
        minPrice: 2000.58,
        medianPrice: 2000.58,
        maxPrice: 2000.58,
      ),
      sources: [
        SourcePriceResult(
          source: source,
          label: source == 'avtopro' ? 'Avto.pro' : 'Prom',
          status: 'ok',
          offersTotal: 1,
          offers: [
            MarketPriceOffer(
              source: source,
              title: 'Амортизатор Opel Omega',
              price: 2000.58,
              currency: 'UAH',
              url: 'https://example.com/offer',
              city: city,
            ),
          ],
        ),
      ],
    );
  }

  Future<void> pump(WidgetTester tester, CompetitorPriceReport data) async {
    tester.view.physicalSize = const Size(700, 1100);
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
            child: CompetitorPricesReport(report: data),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets('avto.pro offer with city explains how to find its price', (
    tester,
  ) async {
    await pump(tester, report(source: 'avtopro', city: 'Харьков'));

    expect(
      find.textContaining('ця ціна в рядку міста Харьков'),
      findsOneWidget,
    );
  });

  testWidgets('avto.pro offer without city shows generic link warning', (
    tester,
  ) async {
    await pump(tester, report(source: 'avtopro'));

    expect(
      find.text('Посилання відкриє всіх продавців деталі'),
      findsOneWidget,
    );
    expect(find.textContaining('ця ціна в рядку міста'), findsNothing);
  });

  testWidgets('prom offer does not show the avto.pro link warning', (
    tester,
  ) async {
    await pump(tester, report(source: 'prom', city: 'Харьков'));

    expect(
      find.textContaining('Посилання відкриє всіх продавців'),
      findsNothing,
    );
  });
}
