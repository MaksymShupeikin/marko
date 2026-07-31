import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:marko_client/core/app_router.dart';
import 'package:marko_client/features/auth/auth_controller.dart';
import 'package:marko_client/features/auth/auth_models.dart';

void main() {
  test('router instance survives auth bootstrap completion', () async {
    final completer = Completer<MarkoAuthState>();
    final container = ProviderContainer(
      overrides: [
        authControllerProvider.overrideWith(
          () => _DelayedAuthController(completer),
        ),
      ],
    );
    addTearDown(container.dispose);

    final before = container.read(appRouterProvider);
    completer.complete(_signedInState);
    await container.read(authControllerProvider.future);
    await Future<void>.delayed(Duration.zero);
    final after = container.read(appRouterProvider);

    expect(identical(after, before), isTrue);
  });

  test('auth bootstrap preserves the requested protected route', () {
    expect(
      authRedirectTarget(
        auth: const AsyncLoading<MarkoAuthState>(),
        matchedLocation: '/',
      ),
      isNull,
    );
    expect(
      authRedirectTarget(
        auth: const AsyncLoading<MarkoAuthState>(),
        matchedLocation: '/catalog/products/product-1',
      ),
      isNull,
    );
    expect(
      authRedirectTarget(
        auth: const AsyncData(MarkoAuthState.initial),
        matchedLocation: '/catalog/products/product-1',
      ),
      '/login',
    );
  });

  test(
    'router exposes stable catalog and recommendation entity paths',
    () async {
      final container = ProviderContainer(
        overrides: [
          authControllerProvider.overrideWith(_SignedInAuthController.new),
        ],
      );
      addTearDown(container.dispose);
      await container.read(authControllerProvider.future);

      final router = container.read(appRouterProvider);
      final routes = router.configuration.routes.whereType<GoRoute>().toList();

      expect(
        routes.singleWhere((route) => route.name == 'pricing').path,
        '/pricing',
      );
      expect(
        routes.singleWhere((route) => route.name == 'catalog').path,
        '/catalog',
      );
      expect(
        routes.singleWhere((route) => route.name == 'stores').path,
        '/stores',
      );
      expect(
        routes.singleWhere((route) => route.name == 'overview').path,
        '/overview',
      );
      expect(
        routes.singleWhere((route) => route.name == 'catalog-product').path,
        '/catalog/products/:productId',
      );
      expect(
        routes
            .singleWhere((route) => route.name == 'pricing-recommendation')
            .path,
        '/pricing/recommendations/:recommendationId',
      );
    },
  );
}

class _SignedInAuthController extends AuthController {
  @override
  Future<MarkoAuthState> build() async => _signedInState;
}

class _DelayedAuthController extends AuthController {
  _DelayedAuthController(this.completer);

  final Completer<MarkoAuthState> completer;

  @override
  Future<MarkoAuthState> build() => completer.future;
}

const _signedInState = MarkoAuthState(
  user: AuthUser(
    id: 'user-1',
    email: 'owner@example.test',
    displayName: 'Owner',
    avatarUrl: null,
    workspaceId: 'workspace-1',
    workspaceRole: 'owner',
  ),
  busy: false,
  error: null,
  notice: null,
);
