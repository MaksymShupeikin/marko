import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:heroicons/heroicons.dart';
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
            icon: HeroIcons.plus,
            onPressed: () => presses++,
          ),
        ),
      ),
    );

    await tester.tap(find.text('Подключить'));
    await tester.pumpAndSettle();

    expect(presses, 1);
  });

  testWidgets('the primary highlight sits on the top edge', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: Scaffold(
          body: Center(
            child: MarkoButton(label: 'Импорт', onPressed: () {}),
          ),
        ),
      ),
    );

    // The highlight rides the gradient, so it is clipped by the corner
    // radius; a positioned stripe would cut straight across them.
    final box =
        tester
                .widget<AnimatedContainer>(
                  find.descendant(
                    of: find.byType(MarkoButton),
                    matching: find.byType(AnimatedContainer),
                  ),
                )
                .decoration
            as BoxDecoration;
    final gradient = box.gradient! as LinearGradient;
    expect(gradient.stops!.first, 0);
    expect(gradient.stops![1] * MarkoLayout.fieldHeight, 1);
    expect(box.borderRadius, BorderRadius.circular(MarkoRadius.md));
    // A border would paint over that first pixel; the ring is a shadow.
    expect(box.border, isNull);
    expect(box.boxShadow!.last.spreadRadius, 1);
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

  testWidgets('MarkoButton.danger renders and invokes callback', (tester) async {
    var pressed = false;
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: Scaffold(
          body: MarkoButton.danger(
            label: 'Видалити',
            icon: HeroIcons.trash,
            onPressed: () => pressed = true,
          ),
        ),
      ),
    );

    expect(find.text('Видалити'), findsOneWidget);
    await tester.tap(find.text('Видалити'));
    await tester.pumpAndSettle();
    expect(pressed, isTrue);
  });
}
