import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/app_router.dart';
import 'core/app_theme.dart';
import 'core/environment.dart';
import 'core/marko_ui.dart';
import 'features/auth/auth_controller.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  if (!Environment.usesAndroidFirebaseConfig &&
      !Environment.hasFirebaseConfig) {
    runApp(
      const _ConfigurationErrorApp(
        'Firebase is not configured. Add the FIREBASE_* dart defines.',
      ),
    );
    return;
  }
  try {
    await Firebase.initializeApp(
      options: Environment.usesAndroidFirebaseConfig
          ? null
          : Environment.firebaseOptions,
    );
  } catch (error) {
    runApp(_ConfigurationErrorApp('Firebase initialization failed: $error'));
    return;
  }
  runApp(const ProviderScope(child: MarkoApp()));
}

class _ConfigurationErrorApp extends StatelessWidget {
  const _ConfigurationErrorApp(this.message);

  final String message;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Marko',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light,
      home: Scaffold(
        body: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 520),
              child: Column(
                children: [
                  const MarkoWordmark(),
                  const SizedBox(height: 24),
                  MarkoInlineMessage(
                    message: message,
                    tone: MarkoMessageTone.error,
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class MarkoApp extends ConsumerWidget {
  const MarkoApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authControllerProvider);
    final themeMode = ref.watch(themeModeProvider);
    if (auth.isLoading) {
      return MaterialApp(
        title: 'Marko',
        debugShowCheckedModeBanner: false,
        theme: AppTheme.light,
        darkTheme: AppTheme.dark,
        themeMode: themeMode,
        builder: AppTheme.touchTargets,
        home: const Scaffold(body: _AppLoading()),
      );
    }
    return MaterialApp.router(
      title: 'Marko',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light,
      darkTheme: AppTheme.dark,
      themeMode: themeMode,
      builder: AppTheme.touchTargets,
      routerConfig: ref.watch(appRouterProvider),
    );
  }
}

class _AppLoading extends StatelessWidget {
  const _AppLoading();

  @override
  Widget build(BuildContext context) {
    return const Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          MarkoWordmark(),
          SizedBox(height: 24),
          SizedBox.square(
            dimension: 22,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
        ],
      ),
    );
  }
}
