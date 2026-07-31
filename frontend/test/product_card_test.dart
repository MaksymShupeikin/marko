import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/stores/store_models.dart';
import 'package:marko_client/features/stores/widgets/product_card.dart';

void main() {
  testWidgets('product card keeps price as the primary visual element', (
    tester,
  ) async {
    final product = StoreProduct(
      id: 'product-id',
      name: 'Premium product',
      url: 'https://prom.ua/product',
      sku: 'SKU-1',
      brand: 'Marko',
      price: 123.45,
      currency: 'UAH',
      isAvailable: true,
      imageUrl: null,
    );
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: Scaffold(
          body: Center(
            child: SizedBox(
              width: 280,
              height: 406,
              child: ProductCard(product: product),
            ),
          ),
        ),
      ),
    );

    final name = tester.widget<Text>(find.text('Premium product'));
    final price = tester.widget<Text>(find.text('123.45'));

    expect(price.style!.fontSize, greaterThan(name.style!.fontSize!));
    expect(find.text('Marko  ·  SKU SKU-1'), findsOneWidget);
    expect(find.text('В наличии'), findsNothing);
  });
}
