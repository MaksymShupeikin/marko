import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/firebase_auth_client.dart';
import 'auth_api.dart';
import 'auth_models.dart';

class AuthController extends AsyncNotifier<MarkoAuthState> {
  AuthApi get _api => ref.read(authApiProvider);
  AuthClient get _auth => ref.read(authClientProvider);
  MarkoAuthState get _current => state.value ?? MarkoAuthState.initial;

  @override
  Future<MarkoAuthState> build() async {
    final auth = ref.watch(authClientProvider);
    final initial = await _stateForSession(auth.currentSession);
    final subscription = auth.authStateChanges.listen(
      (session) {
        if (session != null && !session.emailVerified) return;
        if (session == null && _current.user == null) return;
        unawaited(_syncSession(session));
      },
      onError: (Object error, StackTrace stackTrace) {
        state = AsyncData(
          _current.copyWith(busy: false, error: _message(error)),
        );
      },
    );
    ref.onDispose(() => unawaited(subscription.cancel()));
    return initial;
  }

  Future<void> login(String email, String password) async {
    if (!_validate(email, password)) return;
    state = AsyncData(
      _current.copyWith(busy: true, clearError: true, clearNotice: true),
    );
    try {
      final session = await _auth.login(email.trim().toLowerCase(), password);
      await _syncSession(session);
    } catch (error) {
      _setError(error);
    }
  }

  Future<void> register(String email, String password) async {
    if (!_validate(email, password)) return;
    state = AsyncData(
      _current.copyWith(busy: true, clearError: true, clearNotice: true),
    );
    try {
      await _auth.register(email.trim().toLowerCase(), password);
      state = const AsyncData(
        MarkoAuthState(
          user: null,
          busy: false,
          error: null,
          notice: 'Проверьте почту и подтвердите регистрацию.',
        ),
      );
    } catch (error) {
      _setError(error);
    }
  }

  Future<void> loginWithGoogle() async {
    state = AsyncData(
      _current.copyWith(busy: true, clearError: true, clearNotice: true),
    );
    try {
      final session = await _auth.loginWithGoogle();
      await _syncSession(session);
    } catch (error) {
      _setError(error);
    }
  }

  Future<void> logout() async {
    try {
      await _auth.logout();
    } finally {
      state = const AsyncData(MarkoAuthState.initial);
    }
  }

  Future<void> _syncSession(AuthSession? session) async {
    if (session == null) {
      state = const AsyncData(MarkoAuthState.initial);
      return;
    }
    state = AsyncData(
      _current.copyWith(busy: true, clearError: true, clearNotice: true),
    );
    try {
      final user = await _api.me();
      state = AsyncData(
        MarkoAuthState(user: user, busy: false, error: null, notice: null),
      );
    } catch (error) {
      _setError(error);
    }
  }

  Future<MarkoAuthState> _stateForSession(AuthSession? session) async {
    if (session == null || !session.emailVerified) {
      return MarkoAuthState.initial;
    }
    try {
      return MarkoAuthState(
        user: await _api.me(),
        busy: false,
        error: null,
        notice: null,
      );
    } catch (error) {
      return MarkoAuthState.initial.copyWith(error: _message(error));
    }
  }

  bool _validate(String email, String password) {
    if (!email.trim().contains('@')) {
      state = AsyncData(_current.copyWith(error: 'Введите корректную почту'));
      return false;
    }
    if (password.length < 8) {
      state = AsyncData(
        _current.copyWith(error: 'Пароль должен содержать минимум 8 символов'),
      );
      return false;
    }
    return true;
  }

  void _setError(Object error) {
    state = AsyncData(_current.copyWith(busy: false, error: _message(error)));
  }

  String _message(Object error) {
    if (error is AuthClientException) return error.message;
    return error.toString().replaceFirst('Exception: ', '');
  }
}

final authControllerProvider =
    AsyncNotifierProvider<AuthController, MarkoAuthState>(AuthController.new);
