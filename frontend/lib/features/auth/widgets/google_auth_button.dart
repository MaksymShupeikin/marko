import 'dart:async';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_sign_in/google_sign_in.dart';

import '../../../core/environment.dart';
import '../../../core/firebase_auth_client.dart' show AuthClientException;
import '../../../core/widgets/marko_loader.dart';
import '../auth_controller.dart';
import 'gis_button_stub.dart'
    if (dart.library.js_interop) 'gis_button_web.dart';

/// `init()` blows up if it runs twice, so the whole app shares one call.
Future<void>? _initialization;

/// The Google entry point. On the web with a configured client id this is the
/// button Google renders itself (the only way GIS hands out an ID token);
/// everywhere else — and if GIS fails to come up — it is [fallback].
class GoogleAuthButton extends ConsumerStatefulWidget {
  const GoogleAuthButton({
    required this.busy,
    required this.fallback,
    super.key,
  });

  final bool busy;

  /// Our own button, driven by `loginWithGoogle()`.
  final Widget fallback;

  static bool get usesGis => kIsWeb && Environment.googleClientId.isNotEmpty;

  @override
  ConsumerState<GoogleAuthButton> createState() => _GoogleAuthButtonState();
}

class _GoogleAuthButtonState extends ConsumerState<GoogleAuthButton> {
  StreamSubscription<GoogleSignInAuthenticationEvent>? _events;

  @override
  void initState() {
    super.initState();
    if (!GoogleAuthButton.usesGis) return;
    _initialization ??= GoogleSignIn.instance.initialize(
      clientId: Environment.googleClientId,
    );
    // The button click lands here, not in a future we could await.
    _events = GoogleSignIn.instance.authenticationEvents.listen(
      _onEvent,
      onError: (Object error) => ref
          .read(authControllerProvider.notifier)
          .failGoogleSignIn(error),
    );
  }

  @override
  void dispose() {
    unawaited(_events?.cancel());
    super.dispose();
  }

  void _onEvent(GoogleSignInAuthenticationEvent event) {
    if (event is! GoogleSignInAuthenticationEventSignIn) return;
    final idToken = event.user.authentication.idToken;
    final controller = ref.read(authControllerProvider.notifier);
    if (idToken == null || idToken.isEmpty) {
      controller.failGoogleSignIn(
        const AuthClientException('Google не повернув ID token.'),
      );
      return;
    }
    unawaited(controller.loginWithGoogleIdToken(idToken));
  }

  @override
  Widget build(BuildContext context) {
    if (!GoogleAuthButton.usesGis) return widget.fallback;
    final dark = Theme.of(context).brightness == Brightness.dark;

    return SizedBox(
      height: 44,
      child: FutureBuilder<void>(
        future: _initialization,
        builder: (context, snapshot) {
          // GIS не піднявся (немає мережі, чужий домен) — лишається попап.
          if (snapshot.hasError) return widget.fallback;
          if (snapshot.connectionState != ConnectionState.done) {
            return const Center(child: MarkoLoader(size: 20));
          }
          return IgnorePointer(
            ignoring: widget.busy,
            child: LayoutBuilder(
              builder: (context, constraints) =>
                  renderGisButton(width: constraints.maxWidth, dark: dark),
            ),
          );
        },
      ),
    );
  }
}
