import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/app_theme.dart';

double _relativeLuminance(Color color) {
  final argb = color.toARGB32();
  double linear(int channel) {
    final value = channel / 255;
    return value <= 0.03928
        ? value / 12.92
        : math.pow((value + 0.055) / 1.055, 2.4).toDouble();
  }

  final red = linear((argb >> 16) & 0xff);
  final green = linear((argb >> 8) & 0xff);
  final blue = linear(argb & 0xff);
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

double _contrastRatio(Color foreground, Color background) {
  final first = _relativeLuminance(foreground);
  final second = _relativeLuminance(background);
  return (math.max(first, second) + 0.05) / (math.min(first, second) + 0.05);
}

void main() {
  test('warning and error inline text satisfy WCAG AA contrast', () {
    final colors = MarkoTheme.light;
    final pairs = <String, (Color, Color)>{
      'warning': (colors.warning, colors.warningSoft),
      'error': (colors.negative, colors.negativeSoft),
    };

    for (final MapEntry(key: name, value: pair) in pairs.entries) {
      expect(
        _contrastRatio(pair.$1, pair.$2),
        greaterThanOrEqualTo(4.5),
        reason: '$name inline text must satisfy WCAG AA 4.5:1',
      );
    }
  });

  testWidgets('themed IconButton target is at least 44 pt', (tester) async {
    final theme = AppTheme.light;
    final configuredMinimum = theme.iconButtonTheme.style?.minimumSize?.resolve(
      const <WidgetState>{},
    );
    expect(configuredMinimum, isNotNull);
    expect(configuredMinimum!.width, greaterThanOrEqualTo(44));
    expect(configuredMinimum.height, greaterThanOrEqualTo(44));

    await tester.pumpWidget(
      MaterialApp(
        theme: theme,
        home: Scaffold(
          body: IconButton(
            tooltip: 'Close',
            onPressed: () {},
            icon: const Icon(Icons.close),
          ),
        ),
      ),
    );

    final size = tester.getSize(find.byType(IconButton));
    expect(size.width, greaterThanOrEqualTo(44));
    expect(size.height, greaterThanOrEqualTo(44));
  });
}
