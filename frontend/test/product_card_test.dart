import 'dart:ui' show PointerDeviceKind;

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
  });

  testWidgets('multi-store badge is revealed on hover', (tester) async {
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
      groupSize: 3,
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

    // Badge widget exists in the tree with opacity 0 before hover
    final badgeOpacity = tester.widget<AnimatedOpacity>(
      find.ancestor(
        of: find.byTooltip('У 3 магазинах'),
        matching: find.byType(AnimatedOpacity),
      ),
    );
    expect(badgeOpacity.opacity, 0);

    // Hover reveals the badge
    final gesture = await tester.createGesture(kind: PointerDeviceKind.mouse);
    await gesture.addPointer(location: tester.getCenter(find.byType(ProductCard)));
    await gesture.moveTo(tester.getCenter(find.byType(ProductCard)));
    await tester.pumpAndSettle();

    final hoveredOpacity = tester.widget<AnimatedOpacity>(
      find.ancestor(
        of: find.byTooltip('У 3 магазинах'),
        matching: find.byType(AnimatedOpacity),
      ),
    );
    expect(hoveredOpacity.opacity, 1);
    expect(find.text('3'), findsOneWidget);
  });
}
