import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/firebase_auth_client.dart';
import 'package:marko_client/main.dart';

void main() {
  testWidgets('renders the email and OAuth sign-in screen', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          authClientProvider.overrideWithValue(_SignedOutAuthClient()),
        ],
        child: const MarkoApp(),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Marko'), findsOneWidget);
    expect(find.text('Почта'), findsOneWidget);
    expect(find.text('Пароль'), findsOneWidget);
    expect(find.text('Продолжить с Google'), findsOneWidget);
  });
}

class _SignedOutAuthClient implements AuthClient {
  @override
  Stream<AuthSession?> get authStateChanges => const Stream.empty();

  @override
  AuthSession? get currentSession => null;

  @override
  Future<String?> idToken({bool forceRefresh = false}) async => null;

  @override
  Future<AuthSession> login(String email, String password) =>
      throw UnimplementedError();

  @override
  Future<AuthSession> loginWithGoogle() => throw UnimplementedError();

  @override
  Future<void> logout() async {}

  @override
  Future<void> register(String email, String password) =>
      throw UnimplementedError();
}
