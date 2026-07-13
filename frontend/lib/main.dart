import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/app_router.dart';
import 'core/app_theme.dart';
import 'core/environment.dart';
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
      debugShowCheckedModeBanner: false,
      home: Scaffold(
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Text(message, textAlign: TextAlign.center),
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
    if (auth.isLoading) {
      return MaterialApp(
        title: 'Marko',
        debugShowCheckedModeBanner: false,
        theme: AppTheme.light,
        home: const Scaffold(body: Center(child: CircularProgressIndicator())),
      );
    }
    return MaterialApp.router(
      title: 'Marko',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light,
      routerConfig: ref.watch(appRouterProvider),
    );
  }
}
