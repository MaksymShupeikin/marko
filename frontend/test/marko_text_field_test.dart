import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/core/marko_ui.dart';
import 'package:marko_client/core/widgets/marko_button.dart';

void main() {
  testWidgets('a field without a label centres its text', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: Scaffold(
          body: SizedBox(
            width: 200,
            child: MarkoTextField(
              controller: TextEditingController(text: '1234'),
              hintText: 'Цена от',
              prefixText: 'грн ',
            ),
          ),
        ),
      ),
    );

    final field = tester.getRect(find.byType(TextField));
    final text = tester.getRect(find.byType(EditableText));
    expect(field.height, MarkoLayout.fieldHeight);
    // Off-centre by more than a pixel means the text is stuck to an edge.
    expect((text.center.dy - field.center.dy).abs(), lessThan(1));
  });

  testWidgets('on a phone-width screen fields and buttons reach 48px', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light,
        home: Scaffold(
          body: Column(
            children: [
              MarkoTextField(controller: TextEditingController()),
              MarkoButton(label: 'Войти', onPressed: () {}),
            ],
          ),
        ),
      ),
    );

    expect(
      tester.getRect(find.byType(TextField)).height,
      MarkoLayout.touchFieldHeight,
    );
    expect(
      tester.getRect(find.byType(MarkoButton)).height,
      MarkoLayout.touchFieldHeight,
    );
  });
}
