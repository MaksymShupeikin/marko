import 'dart:convert';

import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_sign_in/google_sign_in.dart';

class AuthSession {
  const AuthSession({
    required this.uid,
    required this.email,
    required this.emailVerified,
  });

  final String uid;
  final String? email;
  final bool emailVerified;
}

class AuthClientException implements Exception {
  const AuthClientException(this.message);

  final String message;

  @override
  String toString() => message;
}

abstract interface class AuthClient {
  AuthSession? get currentSession;
  Stream<AuthSession?> get authStateChanges;

  Future<AuthSession> login(String email, String password);
  Future<void> register(String email, String password);
  Future<AuthSession> loginWithGoogle();

  /// For the web GIS button, which produces the token itself.
  Future<AuthSession> loginWithGoogleIdToken(String idToken);

  /// Also how a Google-only account gets a password: the reset link adds
  /// the password provider to the same Firebase user.
  Future<void> resetPassword(String email);

  /// Email action links land on our /reset-password page, which finishes
  /// them with these calls instead of Firebase's default handler page.
  Future<String> verifyPasswordResetCode(String code);
  Future<void> confirmPasswordReset(String code, String newPassword);
  Future<void> applyActionCode(String code);
  Future<void> logout();
  Future<String?> idToken({bool forceRefresh = false});
}

class FirebaseAuthClient implements AuthClient {
  FirebaseAuthClient(this._auth);

  final FirebaseAuth _auth;
  Future<void>? _googleInitialization;

  /// Editing the console email templates is blocked for this project
  /// (EMAIL_TEMPLATE_UPDATE_NOT_ALLOWED), so instead the default handler at
  /// firebaseapp.com redirects straight here with mode/oobCode — our
  /// /reset-password page finishes the action.
  static final _brandedLink = ActionCodeSettings(
    url: 'https://markoprice.com/',
    handleCodeInApp: true,
  );

  @override
  AuthSession? get currentSession => _toSession(_auth.currentUser);

  @override
  Stream<AuthSession?> get authStateChanges =>
      _auth.authStateChanges().map(_toSession);

  @override
  Future<AuthSession> login(String email, String password) async {
    try {
      final credential = await _auth.signInWithEmailAndPassword(
        email: email,
        password: password,
      );
      final user = _requireUser(credential.user);
      if (!user.emailVerified) {
        await user.sendEmailVerification(_brandedLink);
        await _auth.signOut();
        throw const AuthClientException(
          'Підтвердіть пошту. Ми повторно надіслали лист із посиланням.',
        );
      }
      return _requireSession(user);
    } on FirebaseAuthException catch (error) {
      if (await _isGoogleOnlyAccount(email, error)) {
        throw const AuthClientException(
          'Цей акаунт створено через Google. '
          'Скористайтеся кнопкою «Продовжити з Google».',
        );
      }
      throw AuthClientException(_firebaseMessage(error));
    }
  }

  @override
  Future<void> register(String email, String password) async {
    try {
      final credential = await _auth.createUserWithEmailAndPassword(
        email: email,
        password: password,
      );
      final user = _requireUser(credential.user);
      await user.sendEmailVerification(_brandedLink);
      await _auth.signOut();
    } on FirebaseAuthException catch (error) {
      if (await _isGoogleOnlyAccount(email, error)) {
        throw const AuthClientException(
          'Цей акаунт уже створено через Google. '
          'Скористайтеся кнопкою «Продовжити з Google».',
        );
      }
      throw AuthClientException(_firebaseMessage(error));
    }
  }

  /// firebase_auth 6 removed fetchSignInMethodsForEmail, so we ask the same
  /// Identity Toolkit endpoint directly. Needs email enumeration protection
  /// disabled in Firebase, otherwise signinMethods always comes back empty.
  Future<bool> _isGoogleOnlyAccount(
    String email,
    FirebaseAuthException error,
  ) async {
    const relevant = {
      'invalid-credential',
      'wrong-password',
      'user-not-found',
      'email-already-in-use',
    };
    if (!relevant.contains(error.code)) return false;
    try {
      final response = await http.post(
        Uri.parse(
          'https://identitytoolkit.googleapis.com/v1/accounts:createAuthUri'
          '?key=${_auth.app.options.apiKey}',
        ),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'identifier': email,
          'continueUri': 'http://localhost',
        }),
      );
      if (response.statusCode != 200) return false;
      final methods =
          ((jsonDecode(response.body) as Map<String, dynamic>)['signinMethods']
                  as List?)
              ?.cast<String>() ??
          const [];
      return methods.contains('google.com') && !methods.contains('password');
    } on Exception {
      return false;
    }
  }

  @override
  Future<AuthSession> loginWithGoogle() async {
    try {
      UserCredential credential;
      if (kIsWeb) {
        // google_sign_in has no programmatic sign-in on the web — it only
        // renders its own button. Firebase's popup does the same job here.
        credential = await _auth.signInWithPopup(GoogleAuthProvider());
      } else if (defaultTargetPlatform == TargetPlatform.android ||
          defaultTargetPlatform == TargetPlatform.iOS ||
          defaultTargetPlatform == TargetPlatform.macOS) {
        _googleInitialization ??= GoogleSignIn.instance.initialize();
        await _googleInitialization;
        final account = await GoogleSignIn.instance.authenticate();
        final googleAuthentication = account.authentication;
        final idToken = googleAuthentication.idToken;
        if (idToken == null || idToken.isEmpty) {
          throw const AuthClientException(
            'Google не повернув ID token. Перевірте OAuth client та SHA-1.',
          );
        }
        credential = await _auth.signInWithCredential(
          GoogleAuthProvider.credential(idToken: idToken),
        );
      } else {
        throw const AuthClientException(
          'Google-вхід недоступний у нативній Windows-версії. '
          'Використовуйте web/PWA або вхід поштою.',
        );
      }
      return _requireSession(_requireUser(credential.user));
    } on FirebaseAuthException catch (error) {
      if (error.code == 'popup-closed-by-user' ||
          error.code == 'cancelled-popup-request') {
        throw const AuthClientException('canceled');
      }
      throw AuthClientException(_firebaseMessage(error));
    } on GoogleSignInException catch (error) {
      if (error.code == GoogleSignInExceptionCode.canceled) {
        throw const AuthClientException('canceled');
      }
      throw AuthClientException(
        error.description ?? 'Помилка входу через Google.',
      );
    } catch (error) {
      final msg = error.toString().toLowerCase();
      if (msg.contains('cancel') ||
          msg.contains('closed by user') ||
          msg.contains('popup-closed') ||
          msg.contains('popup_closed')) {
        throw const AuthClientException('canceled');
      }
      rethrow;
    }
  }

  @override
  Future<AuthSession> loginWithGoogleIdToken(String idToken) async {
    try {
      final credential = await _auth.signInWithCredential(
        GoogleAuthProvider.credential(idToken: idToken),
      );
      return _requireSession(_requireUser(credential.user));
    } on FirebaseAuthException catch (error) {
      throw AuthClientException(_firebaseMessage(error));
    }
  }

  @override
  Future<void> resetPassword(String email) async {
    try {
      await _auth.sendPasswordResetEmail(
        email: email,
        actionCodeSettings: _brandedLink,
      );
    } on FirebaseAuthException catch (error) {
      throw AuthClientException(_firebaseMessage(error));
    }
  }

  @override
  Future<String> verifyPasswordResetCode(String code) async {
    try {
      return await _auth.verifyPasswordResetCode(code);
    } on FirebaseAuthException catch (error) {
      throw AuthClientException(_firebaseMessage(error));
    }
  }

  @override
  Future<void> confirmPasswordReset(String code, String newPassword) async {
    try {
      await _auth.confirmPasswordReset(code: code, newPassword: newPassword);
    } on FirebaseAuthException catch (error) {
      throw AuthClientException(_firebaseMessage(error));
    }
  }

  @override
  Future<void> applyActionCode(String code) async {
    try {
      await _auth.applyActionCode(code);
    } on FirebaseAuthException catch (error) {
      throw AuthClientException(_firebaseMessage(error));
    }
  }

  @override
  Future<void> logout() async {
    await _auth.signOut();
    try {
      // Also clears the GIS auto-select on the web; unimplemented on Windows.
      await GoogleSignIn.instance.signOut();
    } catch (_) {
      // Firebase is already signed out; Google cleanup is best-effort.
    }
  }

  @override
  Future<String?> idToken({bool forceRefresh = false}) {
    final user = _auth.currentUser;
    if (user == null || !user.emailVerified) return Future.value();
    return user.getIdToken(forceRefresh);
  }

  static AuthSession? _toSession(User? user) {
    return user == null
        ? null
        : AuthSession(
            uid: user.uid,
            email: user.email,
            emailVerified: user.emailVerified,
          );
  }

  static User _requireUser(User? user) {
    if (user == null) {
      throw const AuthClientException('Firebase не повернув користувача.');
    }
    return user;
  }

  static AuthSession _requireSession(User user) {
    final session = _toSession(user);
    if (session == null) {
      throw const AuthClientException('Firebase не створив сесію.');
    }
    return session;
  }

  static String _firebaseMessage(FirebaseAuthException error) {
    return switch (error.code) {
      'invalid-email' => 'Введіть коректну пошту.',
      'invalid-credential' ||
      'user-not-found' ||
      'wrong-password' => 'Невірна пошта або пароль.',
      'email-already-in-use' => 'Акаунт із цією поштою вже існує.',
      'weak-password' => 'Пароль занадто простий.',
      'user-disabled' => 'Цей акаунт вимкнено.',
      'operation-not-allowed' =>
        'Цей спосіб входу не ввімкнено у Firebase Authentication.',
      'popup-closed-by-user' ||
      'cancelled-popup-request' => 'Вхід через Google скасовано.',
      'popup-blocked' => 'Браузер заблокував вікно входу через Google.',
      'network-request-failed' => 'Немає з’єднання з Firebase.',
      'expired-action-code' => 'Посилання застаріло. Запросіть новий лист.',
      'invalid-action-code' => 'Посилання недійсне або вже використане.',
      'account-exists-with-different-credential' =>
        'Акаунт із цією поштою вже використовує інший спосіб входу.',
      _ => error.message ?? 'Помилка Firebase Authentication.',
    };
  }
}

final authClientProvider = Provider<AuthClient>((ref) {
  return FirebaseAuthClient(FirebaseAuth.instance);
});
