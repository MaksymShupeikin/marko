import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/products/widgets/help_overlay.dart';

void main() {
  testWidgets('help overlay explains the flow and closes again on desktop', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1024, 768);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: Scaffold(
          body: Builder(
            builder: (context) => TextButton(
              onPressed: () => showHelpOverlay(context),
              child: const Text('Інструкція'),
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.text('Інструкція'));
    await tester.pumpAndSettle();
    expect(find.text('Як працює Marko'), findsOneWidget);

    await tester.tap(find.text('Зрозуміло'));
    await tester.pumpAndSettle();
    expect(find.text('Як працює Marko'), findsNothing);
  });

  testWidgets('help overlay opens as branded bottom sheet on mobile', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: Scaffold(
          body: Builder(
            builder: (context) => TextButton(
              onPressed: () => showHelpOverlay(context),
              child: const Text('Інструкція'),
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.text('Інструкція'));
    await tester.pumpAndSettle();
    expect(find.text('Як працює Marko'), findsOneWidget);

    await tester.tap(find.text('Зрозуміло'));
    await tester.pumpAndSettle();
    expect(find.text('Як працює Marko'), findsNothing);
  });
}
