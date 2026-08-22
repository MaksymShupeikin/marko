import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_sign_in/google_sign_in.dart';

import 'environment.dart';

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
  Future<void> logout();
  Future<String?> idToken({bool forceRefresh = false});
}

class FirebaseAuthClient implements AuthClient {
  FirebaseAuthClient(this._auth);

  final FirebaseAuth _auth;
  Future<void>? _googleInitialization;

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
        await user.sendEmailVerification();
        await _auth.signOut();
        throw const AuthClientException(
          'Підтвердіть пошту. Ми повторно надіслали лист із посиланням.',
        );
      }
      return _requireSession(user);
    } on FirebaseAuthException catch (error) {
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
      await user.sendEmailVerification();
      await _auth.signOut();
    } on FirebaseAuthException catch (error) {
      throw AuthClientException(_firebaseMessage(error));
    }
  }

  @override
  Future<AuthSession> loginWithGoogle() async {
    try {
      UserCredential credential;
      if (kIsWeb) {
        if (Environment.googleClientId.isNotEmpty) {
          try {
            _googleInitialization ??= GoogleSignIn.instance.initialize(
              clientId: Environment.googleClientId,
            );
            await _googleInitialization;
            final account = await GoogleSignIn.instance.authenticate();
            final googleAuthentication = account.authentication;
            final idToken = googleAuthentication.idToken;
            if (idToken == null || idToken.isEmpty) {
              throw const AuthClientException('canceled');
            }
            credential = await _auth.signInWithCredential(
              GoogleAuthProvider.credential(idToken: idToken),
            );
          } on GoogleSignInException catch (e) {
            if (e.code == GoogleSignInExceptionCode.canceled) {
              throw const AuthClientException('canceled');
            }
            throw AuthClientException(
              e.description ?? 'Вхід через Google скасовано.',
            );
          } catch (e) {
            final msg = e.toString().toLowerCase();
            if (msg.contains('cancel') ||
                msg.contains('closed') ||
                msg.contains('abort') ||
                msg.contains('popup_closed')) {
              throw const AuthClientException('canceled');
            }
            rethrow;
          }
        } else {
          try {
            credential = await _auth.signInWithPopup(GoogleAuthProvider());
          } on FirebaseAuthException catch (e) {
            if (e.code == 'popup-closed-by-user' ||
                e.code == 'cancelled-popup-request') {
              throw const AuthClientException('canceled');
            }
            rethrow;
          }
        }
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
  Future<void> logout() async {
    await _auth.signOut();
    if (!kIsWeb &&
        (defaultTargetPlatform == TargetPlatform.android ||
            defaultTargetPlatform == TargetPlatform.iOS ||
            defaultTargetPlatform == TargetPlatform.macOS)) {
      try {
        await GoogleSignIn.instance.signOut();
      } catch (_) {
        // Firebase is already signed out; Google cleanup is best-effort.
      }
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
      'account-exists-with-different-credential' =>
        'Акаунт із цією поштою вже використовує інший спосіб входу.',
      _ => error.message ?? 'Помилка Firebase Authentication.',
    };
  }
}

final authClientProvider = Provider<AuthClient>((ref) {
  return FirebaseAuthClient(FirebaseAuth.instance);
});
