import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../features/auth/auth_controller.dart';
import '../features/auth/auth_page.dart';
import '../features/auth/reset_password_page.dart';
import '../features/dashboard/dashboard_page.dart';

/// Firebase email links carry mode/oobCode as query params before the URL
/// fragment, so go_router never sees them. Consumed by the first router build
/// only: login/logout recreate the router and must not drag the user back.
String? _pendingActionLink = _firebaseActionLink();

String? _firebaseActionLink() {
  final params = Uri.base.queryParameters;
  final code = params['oobCode'];
  if (code == null || code.isEmpty) return null;
  return Uri(
    path: '/reset-password',
    queryParameters: {
      'mode': params['mode'] ?? 'resetPassword',
      'oobCode': code,
    },
  ).toString();
}

final appRouterProvider = Provider<GoRouter>((ref) {
  final signedIn = ref.watch(
    authControllerProvider.select((auth) => auth.value?.user != null),
  );
  final router = GoRouter(
    initialLocation: _pendingActionLink ?? '/',
    routes: [
      GoRoute(path: '/', builder: (_, _) => const DashboardPage()),
      GoRoute(path: '/login', builder: (_, _) => const AuthPage()),
      GoRoute(
        path: '/reset-password',
        builder: (_, state) => ResetPasswordPage(
          mode: state.uri.queryParameters['mode'] ?? 'resetPassword',
          oobCode: state.uri.queryParameters['oobCode'] ?? '',
        ),
      ),
    ],
    redirect: (_, state) {
      final path = state.matchedLocation;
      if (path == '/reset-password') return null;
      final publicRoute = path == '/login';
      if (!signedIn && !publicRoute) return '/login';
      if (signedIn && publicRoute) return '/';
      return null;
    },
  );
  _pendingActionLink = null;
  ref.onDispose(router.dispose);
  return router;
});
