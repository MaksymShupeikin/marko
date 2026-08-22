import 'dart:async';
import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/core/firebase_auth_client.dart';
import 'package:marko_client/features/auth/auth_api.dart';
import 'package:marko_client/features/auth/auth_controller.dart';
import 'package:marko_client/features/products/products_api.dart';
import 'package:marko_client/features/products/products_controller.dart';

/// Serves whatever the account named by [uid] is allowed to see.
class _Backend {
  _Backend(this.uid);

  String uid;

  static const _catalog = {'a': 'Радіатор Iveco', 'b': 'Термостат Ford'};

  ApiClient client() => ApiClient(
    client: MockClient((request) async {
      final body = switch (request.url.path) {
        '/api/v1/auth/me' => jsonEncode({
          'id': 'user-$uid',
          'email': '$uid@example.com',
          'display_name': null,
          'avatar_url': null,
          'workspace_id': 'workspace-$uid',
        }),
        '/api/v1/products' => jsonEncode({
          'items': [
            {
              'id': 'p-$uid',
              'external_id': 'p-$uid',
              'name': _catalog[uid],
              'url': 'https://example.test/p-$uid',
              'sku': null,
              'model_id': null,
              'brand': null,
              'currency': 'UAH',
              'current_price': 100,
              'is_available': true,
              'image_url': null,
              'last_seen_at': '2026-08-21T10:00:00Z',
              'store_id': 'store-$uid',
              'store_name': 'store-$uid',
              'marketplace': 'prom',
              'oem_numbers': <String>[],
            },
          ],
          'total': 1,
          'limit': 60,
          'offset': 0,
        }),
        _ => '{}',
      };
      return http.Response(
        body,
        200,
        headers: {'content-type': 'application/json; charset=utf-8'},
      );
    }),
    baseUrl: 'http://api.test',
  );
}

class _FakeAuthClient implements AuthClient {
  final _sessions = StreamController<AuthSession?>.broadcast();

  @override
  AuthSession? get currentSession => null;

  @override
  Stream<AuthSession?> get authStateChanges => _sessions.stream;

  void signIn(String uid) => _sessions.add(
    AuthSession(uid: uid, email: '$uid@example.com', emailVerified: true),
  );

  @override
  Future<void> logout() async => _sessions.add(null);

  @override
  Future<String?> idToken({bool forceRefresh = false}) async => 'token';

  @override
  Future<AuthSession> login(String email, String password) =>
      throw UnimplementedError();

  @override
  Future<AuthSession> loginWithGoogle() => throw UnimplementedError();

  @override
  Future<void> register(String email, String password) =>
      throw UnimplementedError();
}

void main() {
  test('signing in as another account drops the previous catalog', () async {
    final backend = _Backend('a');
    final auth = _FakeAuthClient();
    final api = backend.client();
    final container = ProviderContainer(
      overrides: [
        authClientProvider.overrideWithValue(auth),
        authApiProvider.overrideWithValue(AuthApi(api)),
        productsApiProvider.overrideWithValue(ProductsApi(api)),
      ],
    );
    addTearDown(container.dispose);

    // The catalog stays subscribed, the way the dashboard keeps it alive.
    final subscription = container.listen(
      productsControllerProvider,
      (_, _) {},
    );
    await container.read(authControllerProvider.future);
    auth.signIn('a');
    await container.read(authControllerProvider.future);
    await container.read(productsControllerProvider.future);
    expect(subscription.read().value?.page.items.single.name, 'Радіатор Iveco');

    backend.uid = 'b';
    auth.signIn('b');
    await pumpEventQueue();
    await container.read(authControllerProvider.future);

    final catalog = await container.read(productsControllerProvider.future);
    expect(catalog.page.items.single.name, 'Термостат Ford');
  });
}
