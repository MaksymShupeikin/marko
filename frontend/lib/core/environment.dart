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
  static const firebaseIosAppId = String.fromEnvironment('FIREBASE_IOS_APP_ID');
  static const firebaseIosApiKey = String.fromEnvironment('FIREBASE_IOS_API_KEY');

  /// Web only: with it the page shows Google's own GIS button, without it the
  /// Firebase popup.
  static const googleClientId = String.fromEnvironment(
    'GOOGLE_CLIENT_ID',
    defaultValue:
        '779526440182-nrkjp7e7pma5lhdandq69hcc5gt0aodu.apps.googleusercontent.com',
  );

  static bool get isApplePlatform =>
      !kIsWeb &&
      (defaultTargetPlatform == TargetPlatform.iOS ||
          defaultTargetPlatform == TargetPlatform.macOS);

  static bool get usesNativeFirebaseConfig =>
      !kIsWeb &&
      (defaultTargetPlatform == TargetPlatform.android ||
          defaultTargetPlatform == TargetPlatform.iOS);

  static bool get hasFirebaseConfig =>
      isApplePlatform ||
      (firebaseApiKey.isNotEmpty &&
          firebaseAuthDomain.isNotEmpty &&
          firebaseProjectId.isNotEmpty &&
          firebaseMessagingSenderId.isNotEmpty &&
          firebaseWebAppId.isNotEmpty);

  static FirebaseOptions get firebaseOptions {
    if (isApplePlatform) {
      return FirebaseOptions(
        apiKey: firebaseIosApiKey.isNotEmpty
            ? firebaseIosApiKey
            : (firebaseApiKey.isNotEmpty
                ? firebaseApiKey
                : 'AIzaSyDhdhtX-CGLyR-PxOQbJOWC4Hu7L4AvjBY'),
        appId: firebaseIosAppId.isNotEmpty
            ? firebaseIosAppId
            : '1:779526440182:ios:46665092bb7e5ed97cd8d7',
        messagingSenderId: firebaseMessagingSenderId.isNotEmpty
            ? firebaseMessagingSenderId
            : '779526440182',
        projectId: firebaseProjectId.isNotEmpty
            ? firebaseProjectId
            : 'marko-4941e',
        authDomain: firebaseAuthDomain.isNotEmpty
            ? firebaseAuthDomain
            : 'marko-4941e.firebaseapp.com',
        iosBundleId: 'com.mshupeikin.marko',
        iosClientId:
            '779526440182-jkqhf08di79ts3r5ngol2v22d6234tu8.apps.googleusercontent.com',
        storageBucket: 'marko-4941e.firebasestorage.app',
      );
    }
    return FirebaseOptions(
      apiKey: firebaseApiKey,
      appId: firebaseWebAppId,
      messagingSenderId: firebaseMessagingSenderId,
      projectId: firebaseProjectId,
      authDomain: firebaseAuthDomain,
    );
  }

  static bool get supportsGoogleSignIn =>
      kIsWeb ||
      defaultTargetPlatform == TargetPlatform.android ||
      defaultTargetPlatform == TargetPlatform.iOS ||
      defaultTargetPlatform == TargetPlatform.macOS;

  static String get apiBaseUrl {
    if (_configuredApiUrl.isNotEmpty) return _configuredApiUrl;
    return 'https://api.markoprice.com';
  }
}
