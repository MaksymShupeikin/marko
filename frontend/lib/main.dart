import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_web_plugins/url_strategy.dart';
import 'package:toastification/toastification.dart';

import 'core/app_router.dart';
import 'core/app_theme.dart';
import 'core/environment.dart';
import 'core/marko_ui.dart';
import 'core/widgets/marko_loader.dart';
import 'core/widgets/marko_toast.dart';
import 'features/auth/auth_controller.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  usePathUrlStrategy();
  SystemChrome.setSystemUIOverlayStyle(
    const SystemUiOverlayStyle(
      statusBarColor: Colors.transparent,
      systemNavigationBarColor: Colors.transparent,
    ),
  );
  if (!Environment.usesNativeFirebaseConfig &&
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
      options: Environment.usesNativeFirebaseConfig
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

    final isDark = switch (themeMode) {
      ThemeMode.dark => true,
      ThemeMode.light => false,
      ThemeMode.system =>
        MediaQuery.platformBrightnessOf(context) == Brightness.dark,
    };

    final overlayStyle = SystemUiOverlayStyle(
      statusBarColor: Colors.transparent,
      statusBarIconBrightness: isDark ? Brightness.light : Brightness.dark,
      statusBarBrightness: isDark ? Brightness.dark : Brightness.light,
      systemNavigationBarColor: Colors.transparent,
      systemNavigationBarIconBrightness:
          isDark ? Brightness.light : Brightness.dark,
      systemNavigationBarDividerColor: Colors.transparent,
    );

    if (auth.isLoading) {
      return AnnotatedRegion<SystemUiOverlayStyle>(
        value: overlayStyle,
        child: MaterialApp(
          title: 'Marko',
          debugShowCheckedModeBanner: false,
          theme: AppTheme.light,
          darkTheme: AppTheme.dark,
          themeMode: themeMode,
          builder: AppTheme.touchTargets,
          home: const Scaffold(body: _AppLoading()),
        ),
      );
    }
    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: overlayStyle,
      child: ToastificationWrapper(
        child: MaterialApp.router(
          title: 'Marko',
          debugShowCheckedModeBanner: false,
          theme: AppTheme.light,
          darkTheme: AppTheme.dark,
          themeMode: themeMode,
          builder: (context, child) => ToastificationConfigProvider(
            config: markoToastConfig(context),
            child: _AuthToasts(child: AppTheme.touchTargets(context, child)),
          ),
          routerConfig: ref.watch(appRouterProvider),
        ),
      ),
    );
  }
}

/// Signing in and out happens from three different places; the confirmation
/// belongs to the session change, not to whichever button triggered it.
class _AuthToasts extends ConsumerWidget {
  const _AuthToasts({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    ref.listen(authControllerProvider, (previous, next) {
      final before = previous?.value?.user;
      final after = next.value?.user;
      if (before?.id == after?.id) return;
      if (after != null) {
        showMarkoToast(
          context,
          title: 'Вітаємо, ${after.shortName}',
          message: 'Ви увійшли в акаунт.',
        );
      } else if (before != null) {
        showMarkoToast(
          context,
          message: 'Ви вийшли з акаунта.',
          tone: MarkoMessageTone.info,
        );
      }
    });
    return child;
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
          MarkoLoader(size: 22),
        ],
      ),
    );
  }
}
