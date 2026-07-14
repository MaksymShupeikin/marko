import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/core/widgets/marko_button.dart';

void main() {
  testWidgets('MarkoButton invokes its callback', (tester) async {
    var presses = 0;
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: Scaffold(
          body: MarkoButton(
            label: 'Подключить',
            icon: Icons.add_rounded,
            onPressed: () => presses++,
          ),
        ),
      ),
    );

    await tester.tap(find.text('Подключить'));
    await tester.pumpAndSettle();

    expect(presses, 1);
  });

  testWidgets('MarkoButton stays inactive while disabled', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: const Scaffold(
          body: MarkoButton(label: 'Недоступно', onPressed: null),
        ),
      ),
    );

    final gesture = tester.widget<GestureDetector>(
      find.descendant(
        of: find.byType(MarkoButton),
        matching: find.byType(GestureDetector),
      ),
    );
    expect(gesture.onTap, isNull);
  });
}
