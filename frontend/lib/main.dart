import 'dart:async';
import 'dart:ui';

import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'core/app_language.dart';
import 'core/app_router.dart';
import 'core/app_theme.dart';
import 'core/api_client.dart';
import 'core/client_error_reporter.dart';
import 'core/environment.dart';
import 'core/marko_ui.dart';
import 'features/auth/auth_controller.dart';

void main() {
  runZonedGuarded(
    () async {
      WidgetsFlutterBinding.ensureInitialized();
      FlutterError.onError = (details) {
        FlutterError.presentError(details);
        unawaited(
          ClientErrorReporter.instance.capture(
            details.exception,
            details.stack ?? StackTrace.current,
            kind: ClientErrorKind.flutter,
          ),
        );
      };
      PlatformDispatcher.instance.onError = (error, stackTrace) {
        unawaited(
          ClientErrorReporter.instance.capture(
            error,
            stackTrace,
            kind: ClientErrorKind.platform,
          ),
        );
        return true;
      };
      await _bootstrap();
    },
    (error, stackTrace) {
      unawaited(
        ClientErrorReporter.instance.capture(
          error,
          stackTrace,
          kind: ClientErrorKind.zone,
        ),
      );
    },
  );
}

Future<void> _bootstrap() async {
  WidgetsFlutterBinding.ensureInitialized();
  if (Environment.e2eMode) {
    if (!Environment.hasValidE2eConfig) {
      runApp(
        const _ConfigurationErrorApp(
          'E2E mode requires a synthetic token of at least 32 characters.',
        ),
      );
      return;
    }
    runApp(const ProviderScope(child: MarkoApp()));
    return;
  }
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
      home: SelectionArea(
        child: Scaffold(
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
      ),
    );
  }
}

class MarkoApp extends ConsumerWidget {
  const MarkoApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authControllerProvider);
    final language = ref.watch(appLanguageProvider);
    final reporter = ClientErrorReporter.instance;
    reporter.attachTransport((event) async {
      await ref
          .read(apiClientProvider)
          .postJson('/api/v1/operations/client-errors', body: event);
    });
    unawaited(reporter.flush());
    if (auth.isLoading) {
      return MaterialApp(
        title: 'Marko',
        debugShowCheckedModeBanner: false,
        theme: AppTheme.light,
        locale: language.locale,
        supportedLocales: AppLanguage.values
            .map((item) => item.locale)
            .toList(growable: false),
        localizationsDelegates: GlobalMaterialLocalizations.delegates,
        home: const SelectionArea(child: Scaffold(body: _AppLoading())),
      );
    }
    return MaterialApp.router(
      title: 'Marko',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light,
      locale: language.locale,
      supportedLocales: AppLanguage.values
          .map((item) => item.locale)
          .toList(growable: false),
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
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
