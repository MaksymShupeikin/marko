import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/core/firebase_auth_client.dart';
import 'package:marko_client/features/pricing/recommendations_page.dart';

/// A 401 is the one API failure the operator can actually resolve, and the only
/// one where retrying the same request is pointless. The shared error view knew
/// what to do with a 403 and fell through to `error.toString()` for a 401, so
/// an expired session was presented as the backend's English
/// "Authentication required" next to a "Повторить" button that could only fail
/// again.
void main() {
  testWidgets('an expired session asks for a sign-in, not for a retry', (
    tester,
  ) async {
    final auth = _RecordingAuthClient();
    var refreshAttempts = 0;
    final client = MockClient(
      (_) async => http.Response(
        jsonEncode({'detail': 'Authentication required'}),
        401,
        headers: {'content-type': 'application/json'},
      ),
    );

    await tester.pumpWidget(
      ProviderScope(
        retry: (_, _) => null,
        overrides: [
          apiClientProvider.overrideWithValue(
            ApiClient(
              client: client,
              baseUrl: 'http://api.test',
              accessToken: () async => 'stale-token',
              refreshSession: () async {
                refreshAttempts += 1;
                return false;
              },
            ),
          ),
          authClientProvider.overrideWithValue(auth),
        ],
        child: MaterialApp(
          theme: AppTheme.light,
          locale: const Locale('ru'),
          supportedLocales: const [Locale('ru'), Locale('uk')],
          localizationsDelegates: GlobalMaterialLocalizations.delegates,
          home: const Scaffold(body: RecommendationsPage()),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(
      refreshAttempts,
      1,
      reason: 'the client refreshes the token once before surfacing a 401',
    );
    expect(
      find.textContaining('Authentication required'),
      findsNothing,
      reason: 'a backend English string is not an answer for a shop owner',
    );
    expect(find.textContaining('Сессия истекла'), findsOneWidget);
    expect(
      find.text('Повторить'),
      findsNothing,
      reason: 'repeating a request with a dead token can only fail again',
    );

    await tester.tap(find.byKey(const ValueKey('marko-reauthenticate')));
    await tester.pumpAndSettle();

    expect(
      auth.logouts,
      1,
      reason:
          'the dead session has to be dropped so the router can ask for a new '
          'sign-in',
    );
  });

  testWidgets('a 403 still explains the missing role and offers no sign-in', (
    tester,
  ) async {
    final auth = _RecordingAuthClient();
    final client = MockClient(
      (_) async => http.Response(
        jsonEncode({
          'detail': {
            'code': 'INSUFFICIENT_WORKSPACE_ROLE',
            'required_roles': ['owner', 'admin'],
            'actual_role': 'member',
          },
        }),
        403,
        headers: {'content-type': 'application/json'},
      ),
    );

    await tester.pumpWidget(
      ProviderScope(
        retry: (_, _) => null,
        overrides: [
          apiClientProvider.overrideWithValue(
            ApiClient(client: client, baseUrl: 'http://api.test'),
          ),
          authClientProvider.overrideWithValue(auth),
        ],
        child: MaterialApp(
          theme: AppTheme.light,
          locale: const Locale('ru'),
          supportedLocales: const [Locale('ru'), Locale('uk')],
          localizationsDelegates: GlobalMaterialLocalizations.delegates,
          home: const Scaffold(body: RecommendationsPage()),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.textContaining('нет доступа'), findsOneWidget);
    expect(find.byKey(const ValueKey('marko-reauthenticate')), findsNothing);
    expect(auth.logouts, 0);
  });
}

class _RecordingAuthClient implements AuthClient {
  int logouts = 0;

  @override
  AuthSession? get currentSession => null;

  @override
  Stream<AuthSession?> get authStateChanges => const Stream.empty();

  @override
  Future<AuthSession> login(String email, String password) async =>
      throw UnimplementedError();

  @override
  Future<void> register(String email, String password) async =>
      throw UnimplementedError();

  @override
  Future<AuthSession> loginWithGoogle() async => throw UnimplementedError();

  @override
  Future<void> logout() async => logouts += 1;

  @override
  Future<String?> idToken({bool forceRefresh = false}) async => null;
}
