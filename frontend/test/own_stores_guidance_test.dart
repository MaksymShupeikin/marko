import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/products/products_api.dart';
import 'package:marko_client/features/products/products_models.dart';
import 'package:marko_client/features/products/widgets/product_details_panel.dart';

void main() {
  testWidgets('own stores use the same offer-card surface as competitors', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(700, 1100);
    tester.view.devicePixelRatio = 1;
    addTearDown(() {
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });

    final client = ApiClient(
      client: MockClient((request) async {
        expect(request.url.path, '/api/v1/products/product-1/siblings');
        return http.Response(
          jsonEncode([
            {
              'id': 'listing-1',
              'store_id': 'store-1',
              'store_name': 'Kemp Auto',
              'current_price': 941,
              'currency': 'UAH',
              'url': 'https://kemp.prom.ua/p1.html',
            },
            {
              'id': 'listing-2',
              'store_id': 'store-2',
              'store_name': 'Parts Auto',
              'current_price': 1100,
              'currency': 'UAH',
              'url': 'https://parts.prom.ua/p1.html',
            },
          ]),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }),
      baseUrl: 'http://api.test',
    );
    final report = CompetitorPriceReport(
      cached: false,
      observedAt: null,
      stats: const CompetitorPriceStats(
        offersTotal: 1,
        sourcesTotal: 1,
        minPrice: 1000,
        medianPrice: 1000,
        maxPrice: 1000,
        recommendedPrice: 950,
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
      price: 940,
      currency: 'UAH',
      isAvailable: true,
      imageUrl: null,
      groupSize: 2,
    );

    await tester.pumpWidget(
      ProviderScope(
        overrides: [productsApiProvider.overrideWithValue(ProductsApi(client))],
        child: MaterialApp(
          theme: AppTheme.light,
          home: Scaffold(
            body: SingleChildScrollView(
              child: CompetitorPricesReport(report: report, product: product),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Ваші магазини'), findsOneWidget);
    expect(find.text('Ваш магазин'), findsNWidgets(2));
    expect(find.text('Kemp Auto'), findsOneWidget);
    expect(find.text('Parts Auto'), findsOneWidget);
    expect(find.text('Відповідає рекомендації'), findsOneWidget);
    expect(find.text('Знизити до 950 ₴'), findsOneWidget);

    BoxDecoration offerDecoration(String text) {
      return tester
          .widgetList<Container>(
            find.ancestor(
              of: find.text(text),
              matching: find.byType(Container),
            ),
          )
          .map((container) => container.decoration)
          .whereType<BoxDecoration>()
          .firstWhere((decoration) => decoration.border != null);
    }

    final ownStore = offerDecoration('Kemp Auto');
    final competitor = offerDecoration('Пропозиція конкурента');
    expect(ownStore.borderRadius, competitor.borderRadius);
    expect(ownStore.border, isNotNull);
    expect(competitor.border, isNotNull);
    expect(ownStore.color, competitor.color);
  });
}
