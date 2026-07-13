import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../features/auth/auth_controller.dart';
import '../features/auth/auth_page.dart';
import '../features/dashboard/dashboard_page.dart';
import '../features/stores/store_products_page.dart';

final appRouterProvider = Provider<GoRouter>((ref) {
  final signedIn = ref.watch(
    authControllerProvider.select((auth) => auth.value?.user != null),
  );
  final router = GoRouter(
    routes: [
      GoRoute(path: '/', builder: (_, _) => const DashboardPage()),
      GoRoute(path: '/login', builder: (_, _) => const AuthPage()),
      GoRoute(
        path: '/stores/:storeId',
        name: 'store-products',
        builder: (_, state) =>
            StoreProductsPage(storeId: state.pathParameters['storeId'] ?? ''),
      ),
    ],
    redirect: (_, state) {
      final path = state.matchedLocation;
      final publicRoute = path == '/login';
      if (!signedIn && !publicRoute) return '/login';
      if (signedIn && publicRoute) return '/';
      return null;
    },
  );
  ref.onDispose(router.dispose);
  return router;
});
