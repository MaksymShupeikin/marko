import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../features/attention/attention_controller.dart';
import '../features/attention/attention_page.dart';
import '../features/auth/auth_controller.dart';
import '../features/auth/auth_models.dart';
import '../features/auth/auth_page.dart';
import '../features/catalog/catalog_controller.dart';
import '../features/catalog/catalog_import_dialog.dart';
import '../features/catalog/catalog_page.dart';
import '../features/dashboard/dashboard_page.dart';
import '../features/pricing/recommendations_page.dart';
import '../features/stores/store_products_page.dart';
import '../features/stores/stores_page.dart';
import 'client_error_reporter.dart';

final appRouterProvider = Provider<GoRouter>((ref) {
  final authRefresh = ref.watch(_authRouterRefreshProvider);
  final router = GoRouter(
    refreshListenable: authRefresh,
    observers: [ClientTelemetryNavigatorObserver(ClientErrorReporter.instance)],
    routes: [
      StatefulShellRoute.indexedStack(
        builder: (context, state, navigationShell) {
          return SelectionArea(
            child: WorkspaceShell(navigationShell: navigationShell),
          );
        },
        redirect: (context, state) {
          if (state.uri.path != '/') return null;
          return switch (state.uri.queryParameters['tab']) {
            'catalog' => '/catalog',
            'stores' => '/stores',
            _ => null,
          };
        },
        branches: [
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: '/',
                name: 'dashboard',
                builder: (context, state) => _attentionBranch(ref),
              ),
              GoRoute(
                path: '/overview',
                name: 'overview',
                builder: (context, state) => _attentionBranch(ref),
              ),
              GoRoute(
                path: '/pricing',
                name: 'pricing',
                builder: (context, state) => _recommendationsBranch(
                  ref,
                  queue: state.uri.queryParameters['queue'],
                  sort: state.uri.queryParameters['sort'],
                  action: state.uri.queryParameters['action'],
                ),
                routes: [
                  GoRoute(
                    path: 'recommendations/:recommendationId',
                    name: 'pricing-recommendation',
                    builder: (context, state) => _recommendationsBranch(
                      ref,
                      recommendationId:
                          state.pathParameters['recommendationId'],
                      queue: state.uri.queryParameters['queue'],
                      sort: state.uri.queryParameters['sort'],
                      action: state.uri.queryParameters['action'],
                    ),
                  ),
                ],
              ),
            ],
          ),
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: '/catalog',
                name: 'catalog',
                builder: (context, state) => _catalogBranch(
                  ref,
                  storeId: state.uri.queryParameters['store'],
                  query: state.uri.queryParameters['q'],
                ),
                routes: [
                  GoRoute(
                    path: 'products/:productId',
                    name: 'catalog-product',
                    builder: (context, state) => _catalogBranch(
                      ref,
                      productId: state.pathParameters['productId'],
                      storeId: state.uri.queryParameters['store'],
                      query: state.uri.queryParameters['q'],
                    ),
                  ),
                ],
              ),
            ],
          ),
          StatefulShellBranch(
            routes: [
              GoRoute(
                path: '/stores',
                name: 'stores',
                builder: (context, state) => _storesBranch(ref),
              ),
            ],
          ),
        ],
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

Widget _attentionBranch(Ref ref) {
  return _WorkspacePage(
    builder: (canAdminister) => AttentionPage(
      onOpenSources: () => ref.read(appRouterProvider).go('/stores'),
      onOpenRecommendation: (id) => ref
          .read(appRouterProvider)
          .goNamed(
            'pricing-recommendation',
            pathParameters: {'recommendationId': id},
          ),
    ),
  );
}

Widget _recommendationsBranch(
  Ref ref, {
  String? recommendationId,
  String? queue,
  String? sort,
  String? action,
}) {
  return _WorkspacePage(
    builder: (canAdminister) => RecommendationsPage(
      canAdministerWorkspace: canAdminister,
      initialRecommendationId: recommendationId,
      initialQueue: queue,
      initialSort: sort,
      initialAction: action,
      onOpenCatalog: () => ref.read(appRouterProvider).go('/catalog'),
      onOpenRecommendationDeepLink: (id) => ref
          .read(appRouterProvider)
          .goNamed(
            'pricing-recommendation',
            pathParameters: {'recommendationId': id},
          ),
    ),
  );
}

Widget _catalogBranch(
  Ref ref, {
  String? productId,
  String? storeId,
  String? query,
}) {
  return _WorkspacePage(
    builder: (canAdminister) => CatalogPage(
      canAdministerWorkspace: canAdminister,
      initialStoreId: storeId,
      initialQuery: query,
      initialProductId: productId,
      onOpenPriceComparison: () => ref.read(appRouterProvider).go('/pricing'),
      onOpenProductDeepLink: (id) => ref
          .read(appRouterProvider)
          .goNamed('catalog-product', pathParameters: {'productId': id}),
    ),
  );
}

Widget _storesBranch(Ref ref) {
  return _WorkspacePage(
    builder: (canAdminister) => StoresPage(
      ownedOnly: true,
      canAdministerWorkspace: canAdminister,
      onOpenStoreCatalog: (storeId) =>
          ref.read(appRouterProvider).go('/catalog?store=$storeId'),
      onImportCatalog: canAdminister
          ? () {
              final context = ref
                  .read(appRouterProvider)
                  .routerDelegate
                  .navigatorKey
                  .currentContext;
              if (context == null) return;
              showCatalogImportDialog(
                context: context,
                canAdministerWorkspace: true,
                onImported: () {
                  ref.invalidate(catalogControllerProvider);
                  ref.invalidate(attentionControllerProvider);
                },
              );
            }
          : null,
    ),
  );
}

class _WorkspacePage extends ConsumerWidget {
  const _WorkspacePage({required this.builder});

  final Widget Function(bool canAdminister) builder;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final canAdminister =
        ref.watch(authControllerProvider).value?.user?.canAdministerWorkspace ??
        false;
    return builder(canAdminister);
  }
}

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
