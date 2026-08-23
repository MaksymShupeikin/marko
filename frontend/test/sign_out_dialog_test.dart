import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/auth/auth_models.dart';
import 'package:marko_client/features/auth/widgets/sign_out_dialog.dart';

void main() {
  const testUser = AuthUser(
    id: 'user-1',
    email: 'alex@example.com',
    displayName: 'Олександр',
    avatarUrl: null,
    workspaceId: 'ws-1',
  );

  Widget testApp(Future<bool?> Function(BuildContext) onTrigger) {
    return MaterialApp(
      theme: AppTheme.light,
      home: Scaffold(
        body: Builder(
          builder: (context) => Center(
            child: ElevatedButton(
              onPressed: () => onTrigger(context),
              child: const Text('Open Dialog'),
            ),
          ),
        ),
      ),
    );
  }

  testWidgets('confirmSignOut displays user info and allows canceling', (
    tester,
  ) async {
    bool? confirmed;
    await tester.pumpWidget(
      testApp((context) async {
        confirmed = await confirmSignOut(context, user: testUser);
        return confirmed;
      }),
    );

    await tester.tap(find.text('Open Dialog'));
    await tester.pumpAndSettle();

    expect(find.text('Вийти з акаунта?'), findsOneWidget);
    expect(find.text('Олександр'), findsOneWidget);
    expect(find.text('alex@example.com'), findsOneWidget);
    expect(
      find.text('Ви зможете в будь-який момент повернутися та увійти знову.'),
      findsOneWidget,
    );

    await tester.tap(find.text('Скасувати'));
    await tester.pumpAndSettle();

    expect(find.text('Вийти з акаунта?'), findsNothing);
    expect(confirmed, isFalse);
  });

  testWidgets('confirmSignOut returns true on confirm button click', (
    tester,
  ) async {
    bool? confirmed;
    await tester.pumpWidget(
      testApp((context) async {
        confirmed = await confirmSignOut(context, user: testUser);
        return confirmed;
      }),
    );

    await tester.tap(find.text('Open Dialog'));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Вийти'));
    await tester.pumpAndSettle();

    expect(find.text('Вийти з акаунта?'), findsNothing);
    expect(confirmed, isTrue);
  });
}
