import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../features/auth/auth_controller.dart';
import '../features/auth/auth_models.dart';
import '../features/auth/auth_page.dart';
import '../features/dashboard/dashboard_page.dart';
import '../features/stores/store_products_page.dart';
import 'client_error_reporter.dart';

final appRouterProvider = Provider<GoRouter>((ref) {
  final authRefresh = ref.watch(_authRouterRefreshProvider);
  final router = GoRouter(
    refreshListenable: authRefresh,
    observers: [ClientTelemetryNavigatorObserver(ClientErrorReporter.instance)],
    routes: [
      GoRoute(
        path: '/',
        name: 'dashboard',
        builder: (_, state) => SelectionArea(
          child: DashboardPage(
            initialTab: switch (state.uri.queryParameters['tab']) {
              'catalog' => 1,
              'stores' => 2,
              _ => 0,
            },
            routeNavigation: true,
          ),
        ),
      ),
      GoRoute(
        path: '/pricing',
        name: 'pricing',
        builder: (_, _) => const SelectionArea(
          child: DashboardPage(
            initialTab: 0,
            legacyPricing: true,
            routeNavigation: true,
          ),
        ),
      ),
      GoRoute(
        path: '/catalog',
        name: 'catalog',
        builder: (_, _) => const SelectionArea(
          child: DashboardPage(initialTab: 1, routeNavigation: true),
        ),
      ),
      GoRoute(
        path: '/stores',
        name: 'stores',
        builder: (_, _) => const SelectionArea(
          child: DashboardPage(initialTab: 2, routeNavigation: true),
        ),
      ),
      GoRoute(
        path: '/overview',
        name: 'overview',
        builder: (_, _) => const SelectionArea(
          child: DashboardPage(initialTab: 0, routeNavigation: true),
        ),
      ),
      GoRoute(
        path: '/login',
        name: 'login',
        builder: (_, _) => const SelectionArea(child: AuthPage()),
      ),
      GoRoute(
        path: '/stores/:storeId',
        name: 'store-products',
        builder: (_, state) => SelectionArea(
          child: StoreProductsPage(
            storeId: state.pathParameters['storeId'] ?? '',
            initialQuery: state.uri.queryParameters['q'] ?? '',
          ),
        ),
      ),
      GoRoute(
        path: '/catalog/products/:productId',
        name: 'catalog-product',
        builder: (_, state) => SelectionArea(
          child: DashboardPage(
            initialCatalogProductId: state.pathParameters['productId'] ?? '',
            routeNavigation: true,
          ),
        ),
      ),
      GoRoute(
        path: '/pricing/recommendations/:recommendationId',
        name: 'pricing-recommendation',
        builder: (_, state) => SelectionArea(
          child: DashboardPage(
            initialRecommendationId:
                state.pathParameters['recommendationId'] ?? '',
            routeNavigation: true,
          ),
        ),
      ),
    ],
    redirect: (_, state) {
      return authRedirectTarget(
        auth: ref.read(authControllerProvider),
        matchedLocation: state.matchedLocation,
      );
    },
  );
  ref.onDispose(router.dispose);
  return router;
});

final _authRouterRefreshProvider = Provider<_AuthRouterRefresh>((ref) {
  final refresh = _AuthRouterRefresh();
  ref.listen<AsyncValue<MarkoAuthState>>(
    authControllerProvider,
    (_, _) => refresh.notify(),
  );
  ref.onDispose(refresh.dispose);
  return refresh;
});

class _AuthRouterRefresh extends ChangeNotifier {
  void notify() => notifyListeners();
}

String? authRedirectTarget({
  required AsyncValue<MarkoAuthState> auth,
  required String matchedLocation,
}) {
  // A cold-start auth check is not proof that the user is signed out. Moving
  // to /login here would discard the requested tab/entity deep link before
  // the persisted session has had a chance to resolve.
  if (auth.isLoading && !auth.hasValue) return null;
  final signedIn = auth.value?.user != null;
  final publicRoute = matchedLocation == '/login';
  if (!signedIn && !publicRoute) return '/login';
  if (signedIn && publicRoute) return '/';
  return null;
}
