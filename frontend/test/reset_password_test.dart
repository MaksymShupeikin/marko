import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/core/firebase_auth_client.dart';
import 'package:marko_client/features/auth/reset_password_page.dart';

void main() {
  Widget page(String mode, String code, AuthClient auth) => ProviderScope(
    overrides: [authClientProvider.overrideWithValue(auth)],
    child: MaterialApp(
      theme: AppTheme.light,
      home: ResetPasswordPage(mode: mode, oobCode: code),
    ),
  );

  testWidgets('verifies the code and sets a new password', (tester) async {
    final auth = _ActionAuthClient();
    await tester.pumpWidget(page('resetPassword', 'code-1', auth));
    await tester.pumpAndSettle();

    expect(find.textContaining('user@example.com'), findsOneWidget);

    await tester.enterText(find.byType(TextField).at(0), 'newpassword1');
    await tester.enterText(find.byType(TextField).at(1), 'newpassword1');
    await tester.tap(find.text('Зберегти пароль'));
    await tester.pumpAndSettle();

    expect(auth.confirmedCode, 'code-1');
    expect(auth.confirmedPassword, 'newpassword1');
    expect(find.textContaining('Пароль змінено'), findsOneWidget);
  });

  testWidgets('rejects mismatched passwords without calling Firebase', (
    tester,
  ) async {
    final auth = _ActionAuthClient();
    await tester.pumpWidget(page('resetPassword', 'code-1', auth));
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField).at(0), 'newpassword1');
    await tester.enterText(find.byType(TextField).at(1), 'different1234');
    await tester.tap(find.text('Зберегти пароль'));
    await tester.pumpAndSettle();

    expect(auth.confirmedCode, isNull);
    expect(find.text('Паролі не збігаються'), findsOneWidget);
  });

  testWidgets('applies verifyEmail links and shows success', (tester) async {
    final auth = _ActionAuthClient();
    await tester.pumpWidget(page('verifyEmail', 'code-2', auth));
    await tester.pumpAndSettle();

    expect(auth.appliedCode, 'code-2');
    expect(find.textContaining('Пошту підтверджено'), findsOneWidget);
  });

  testWidgets('shows an error for an invalid code', (tester) async {
    final auth = _ActionAuthClient()..failVerify = true;
    await tester.pumpWidget(page('resetPassword', 'bad', auth));
    await tester.pumpAndSettle();

    expect(find.text('Посилання недійсне або вже використане.'), findsOneWidget);
    expect(find.text('До входу'), findsOneWidget);
  });
}

class _ActionAuthClient implements AuthClient {
  bool failVerify = false;
  String? confirmedCode;
  String? confirmedPassword;
  String? appliedCode;

  @override
  Future<String> verifyPasswordResetCode(String code) async {
    if (failVerify) {
      throw const AuthClientException('Посилання недійсне або вже використане.');
    }
    return 'user@example.com';
  }

  @override
  Future<void> confirmPasswordReset(String code, String newPassword) async {
    confirmedCode = code;
    confirmedPassword = newPassword;
  }

  @override
  Future<void> applyActionCode(String code) async => appliedCode = code;

  @override
  AuthSession? get currentSession => null;

  @override
  Stream<AuthSession?> get authStateChanges => const Stream.empty();

  @override
  Future<String?> idToken({bool forceRefresh = false}) async => null;

  @override
  Future<AuthSession> login(String email, String password) =>
      throw UnimplementedError();

  @override
  Future<AuthSession> loginWithGoogle() => throw UnimplementedError();

  @override
  Future<AuthSession> loginWithGoogleIdToken(String idToken) =>
      throw UnimplementedError();

  @override
  Future<void> register(String email, String password) =>
      throw UnimplementedError();

  @override
  Future<void> resetPassword(String email) => throw UnimplementedError();

  @override
  Future<void> logout() async {}
}
