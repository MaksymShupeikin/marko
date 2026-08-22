import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/core/marko_ui.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  testWidgets('the toggle flips the app between the light and dark palettes', (
    tester,
  ) async {
    await tester.pumpWidget(
      ProviderScope(
        child: Consumer(
          builder: (context, ref, _) => MaterialApp(
            theme: AppTheme.light,
            darkTheme: AppTheme.dark,
            themeMode: ref.watch(themeModeProvider),
            home: const Scaffold(body: Center(child: MarkoThemeToggle())),
          ),
        ),
      ),
    );

    Color canvas() =>
        MarkoTheme.of(tester.element(find.byType(MarkoThemeToggle))).canvas;

    expect(canvas(), MarkoTheme.light.canvas);

    await tester.tap(find.byType(IconButton));
    await tester.pumpAndSettle();
    expect(canvas(), MarkoTheme.dark.canvas);

    await tester.tap(find.byType(IconButton));
    await tester.pumpAndSettle();
    expect(canvas(), MarkoTheme.light.canvas);
  });

  testWidgets('theme selection persists across reload', (tester) async {
    SharedPreferences.setMockInitialValues({'marko_theme_mode': 'dark'});
    final container = ProviderContainer();
    addTearDown(container.dispose);

    await tester.runAsync(() async {
      container.read(themeModeProvider);
      await Future<void>.delayed(const Duration(milliseconds: 10));
    });
    expect(container.read(themeModeProvider), ThemeMode.dark);
  });
}
