import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/products/widgets/competitor_results.dart';

Widget _host(Widget child) => MaterialApp(
  theme: AppTheme.light,
  home: Scaffold(
    body: Center(child: SizedBox(width: 400, child: child)),
  ),
);

void main() {
  testWidgets('spread bar formats prices and survives a flat spread', (
    tester,
  ) async {
    await tester.pumpWidget(
      _host(
        const PriceSpreadBar(min: 180, median: 245, max: 340, currency: 'UAH'),
      ),
    );
    expect(find.text('180 UAH'), findsOneWidget);
    expect(find.text('245 UAH'), findsOneWidget);
    expect(find.text('340 UAH'), findsOneWidget);

    // min == max would divide by zero when placing the median marker.
    await tester.pumpWidget(
      _host(
        const PriceSpreadBar(min: 200, median: 200, max: 200, currency: 'UAH'),
      ),
    );
    expect(tester.takeException(), isNull);

    await tester.pumpWidget(
      _host(
        const PriceSpreadBar(
          min: null,
          median: null,
          max: null,
          currency: 'UAH',
        ),
      ),
    );
    expect(find.text('—'), findsNWidgets(3));
  });
}
