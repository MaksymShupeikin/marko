import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/core/marko_ui.dart';
import 'package:marko_client/core/widgets/marko_toast.dart';
import 'package:toastification/toastification.dart';

Future<void> _pumpHost(WidgetTester tester, Size size) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);

  await tester.pumpWidget(
    ToastificationWrapper(
      child: MaterialApp(
        theme: AppTheme.light,
        builder: (context, child) => ToastificationConfigProvider(
          config: markoToastConfig(context),
          child: child!,
        ),
        home: Scaffold(
          body: Builder(
            builder: (context) => Center(
              child: TextButton(
                onPressed: () => showMarkoToast(
                  context,
                  title: 'Дані оновлено',
                  message: 'Товар оновлено за посиланням.',
                  tone: MarkoMessageTone.success,
                ),
                child: const Text('go'),
              ),
            ),
          ),
        ),
      ),
    ),
  );
}

void main() {
  testWidgets('desktop toast lands in the top-right corner', (tester) async {
    await _pumpHost(tester, const Size(1400, 900));

    await tester.tap(find.text('go'));
    await tester.pumpAndSettle();

    expect(find.text('Товар оновлено за посиланням.'), findsOneWidget);
    final card = tester.getRect(find.text('Дані оновлено'));
    expect(card.right, greaterThan(1400 * 0.6));
    expect(card.top, lessThan(200));

    toastification.dismissAll(delayForAnimation: false);
    await tester.pump(const Duration(milliseconds: 700));
    await tester.pumpAndSettle();
  });

  testWidgets('phone toast spans the width', (tester) async {
    await _pumpHost(tester, const Size(390, 844));

    await tester.tap(find.text('go'));
    await tester.pumpAndSettle();

    final card = tester.getRect(
      find.ancestor(
        of: find.text('Дані оновлено'),
        matching: find.byType(IntrinsicHeight),
      ),
    );
    expect(card.width, greaterThan(390 * 0.9));
    expect(card.top, lessThan(100));

    // Tapping it takes it away.
    await tester.tap(find.text('Дані оновлено'));
    await tester.pumpAndSettle();
    expect(find.text('Дані оновлено'), findsNothing);
  });
}
