import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/foundation.dart';
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
          'Подтвердите почту. Мы повторно отправили письмо со ссылкой.',
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
            'Google не вернул ID token. Проверьте OAuth client и SHA-1.',
          );
        }
        credential = await _auth.signInWithCredential(
          GoogleAuthProvider.credential(idToken: idToken),
        );
      } else {
        throw const AuthClientException(
          'Google-вход недоступен в нативной Windows-версии. '
          'Используйте web/PWA или вход по почте.',
        );
      }
      return _requireSession(_requireUser(credential.user));
    } on FirebaseAuthException catch (error) {
      throw AuthClientException(_firebaseMessage(error));
    } on GoogleSignInException catch (error) {
      if (error.code == GoogleSignInExceptionCode.canceled) {
        throw const AuthClientException('Вход через Google отменён.');
      }
      throw AuthClientException(
        error.description ?? 'Ошибка входа через Google.',
      );
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
      throw const AuthClientException('Firebase не вернул пользователя.');
    }
    return user;
  }

  static AuthSession _requireSession(User user) {
    final session = _toSession(user);
    if (session == null) {
      throw const AuthClientException('Firebase не создал сессию.');
    }
    return session;
  }

  static String _firebaseMessage(FirebaseAuthException error) {
    return switch (error.code) {
      'invalid-email' => 'Введите корректную почту.',
      'invalid-credential' ||
      'user-not-found' ||
      'wrong-password' => 'Неверная почта или пароль.',
      'email-already-in-use' => 'Аккаунт с этой почтой уже существует.',
      'weak-password' => 'Пароль слишком простой.',
      'user-disabled' => 'Этот аккаунт отключён.',
      'operation-not-allowed' =>
        'Этот способ входа не включён в Firebase Authentication.',
      'popup-closed-by-user' ||
      'cancelled-popup-request' => 'Вход через Google отменён.',
      'popup-blocked' => 'Браузер заблокировал окно входа через Google.',
      'network-request-failed' => 'Нет соединения с Firebase.',
      'account-exists-with-different-credential' =>
        'Аккаунт с этой почтой уже использует другой способ входа.',
      _ => error.message ?? 'Ошибка Firebase Authentication.',
    };
  }
}

final authClientProvider = Provider<AuthClient>((ref) {
  return FirebaseAuthClient(FirebaseAuth.instance);
});
