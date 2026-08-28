import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/products/products_models.dart';
import 'package:marko_client/features/products/widgets/product_card.dart';

void main() {
  testWidgets('product card keeps price as the primary visual element', (
    tester,
  ) async {
    const product = StoreProduct(
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
        home: const Scaffold(
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
    expect(find.text('В наявності'), findsOneWidget);
    expect(find.textContaining('магазин'), findsNothing);
  });

  testWidgets('grouped product card shows the own-store count badge', (
    tester,
  ) async {
    const product = StoreProduct(
      id: 'product-id',
      name: 'Grouped product',
      url: 'https://prom.ua/product',
      sku: 'SKU-1',
      brand: 'Marko',
      price: 1000,
      currency: 'UAH',
      isAvailable: true,
      imageUrl: null,
      storeId: 'store-1',
      storeName: 'KEMP',
      groupSize: 2,
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
      ],
    );

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: const Scaffold(
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

    expect(find.text('у 2 магазинах'), findsOneWidget);
  });
}
