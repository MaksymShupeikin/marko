import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/foundation.dart';

abstract final class Environment {
  static const _configuredApiUrl = String.fromEnvironment('API_BASE_URL');
  static const firebaseApiKey = String.fromEnvironment('FIREBASE_API_KEY');
  static const firebaseAuthDomain = String.fromEnvironment(
    'FIREBASE_AUTH_DOMAIN',
  );
  static const firebaseProjectId = String.fromEnvironment(
    'FIREBASE_PROJECT_ID',
  );
  static const firebaseMessagingSenderId = String.fromEnvironment(
    'FIREBASE_MESSAGING_SENDER_ID',
  );
  static const firebaseWebAppId = String.fromEnvironment('FIREBASE_WEB_APP_ID');
  static const e2eMode = bool.fromEnvironment('E2E_MODE');
  static const e2eAuthToken = String.fromEnvironment('E2E_AUTH_TOKEN');

  static bool get usesAndroidFirebaseConfig =>
      !kIsWeb && defaultTargetPlatform == TargetPlatform.android;

  static bool get hasFirebaseConfig =>
      firebaseApiKey.isNotEmpty &&
      firebaseAuthDomain.isNotEmpty &&
      firebaseProjectId.isNotEmpty &&
      firebaseMessagingSenderId.isNotEmpty &&
      firebaseWebAppId.isNotEmpty;

  static bool get hasValidE2eConfig => e2eMode && e2eAuthToken.length >= 32;

  static FirebaseOptions get firebaseOptions => FirebaseOptions(
    apiKey: firebaseApiKey,
    appId: firebaseWebAppId,
    messagingSenderId: firebaseMessagingSenderId,
    projectId: firebaseProjectId,
    authDomain: firebaseAuthDomain,
  );

  static bool get supportsGoogleSignIn =>
      kIsWeb ||
      defaultTargetPlatform == TargetPlatform.android ||
      defaultTargetPlatform == TargetPlatform.iOS ||
      defaultTargetPlatform == TargetPlatform.macOS;

  static String get apiBaseUrl {
    if (_configuredApiUrl.isNotEmpty) return _configuredApiUrl;
    if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) {
      return 'http://10.0.2.2:8000';
    }
    return 'http://localhost:8000';
  }
}
