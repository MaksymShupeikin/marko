import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/core/marko_motion.dart';
import 'package:marko_client/core/widgets/marko_atmosphere.dart';
import 'package:marko_client/core/widgets/marko_spotlight.dart';

void main() {
  testWidgets('looping atmosphere does not block pumpAndSettle', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: const Scaffold(
          body: MarkoAtmosphere(
            beams: true,
            meteors: true,
            sparkles: true,
            child: Center(child: MarkoFadeUp(child: Text('ready'))),
          ),
        ),
      ),
    );

    await tester.pumpAndSettle();
    expect(find.text('ready'), findsOneWidget);
    expect(markoWidgetTestBinding, isTrue);
    expect(
      markoLoopingMotionEnabled(tester.element(find.text('ready'))),
      isFalse,
    );
  });

  testWidgets('moving border keeps its child visible', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: const Scaffold(body: MarkoMovingBorder(child: Text('bordered'))),
      ),
    );

    await tester.pumpAndSettle();
    expect(find.text('bordered'), findsOneWidget);
  });

  testWidgets('spotlight still builds after a pointer move', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: const Scaffold(
          body: Center(
            child: SizedBox(
              width: 240,
              height: 160,
              child: MarkoSpotlight(child: Text('card')),
            ),
          ),
        ),
      ),
    );

    final gesture = await tester.createGesture(kind: PointerDeviceKind.mouse);
    await gesture.addPointer(location: Offset.zero);
    addTearDown(gesture.removePointer);
    await tester.pump();
    await gesture.moveTo(tester.getCenter(find.text('card')));
    await tester.pump();

    expect(find.byType(MarkoSpotlight), findsOneWidget);
    expect(find.text('card'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
