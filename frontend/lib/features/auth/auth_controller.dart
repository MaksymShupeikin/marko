import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/firebase_auth_client.dart';
import '../products/products_controller.dart';
import '../products/products_page.dart'
    show
        catalogSearchFieldProvider,
        catalogPriceMinFieldProvider,
        catalogPriceMaxFieldProvider;
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
          notice: 'Перевірте пошту та підтвердьте реєстрацію.',
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
      if (_isUserCancellation(error)) {
        state = AsyncData(_current.copyWith(busy: false, clearError: true));
        return;
      }
      _setError(error);
    } finally {
      if (state.value?.busy == true && state.value?.user == null) {
        state = AsyncData(state.value!.copyWith(busy: false));
      }
    }
  }

  Future<void> logout() async {
    try {
      await _auth.logout();
    } finally {
      state = const AsyncData(MarkoAuthState.initial);
      _dropAccountData();
    }
  }

  /// Catalog and stores are per-workspace: the providers are root-scoped, so
  /// without this the next account keeps looking at the previous one's data.
  void _dropAccountData() {
    ref.invalidate(productsControllerProvider);
    ref.invalidate(catalogImportProvider);
    // Invalidating would dispose a controller the search field may still hold.
    ref.read(catalogSearchFieldProvider).clear();
    ref.read(catalogPriceMinFieldProvider).clear();
    ref.read(catalogPriceMaxFieldProvider).clear();
  }

  Future<void> _syncSession(AuthSession? session) async {
    final previous = _current.user?.id;
    if (session == null) {
      state = const AsyncData(MarkoAuthState.initial);
      if (previous != null) _dropAccountData();
      return;
    }
    state = AsyncData(
      _current.copyWith(busy: true, clearError: true, clearNotice: true),
    );
    try {
      final user = await _api.me();
      if (user.id != previous) _dropAccountData();
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
      state = AsyncData(_current.copyWith(error: 'Введіть коректну пошту'));
      return false;
    }
    if (password.length < 8) {
      state = AsyncData(
        _current.copyWith(error: 'Пароль має містити щонайменше 8 символів'),
      );
      return false;
    }
    return true;
  }

  void _setError(Object error) {
    state = AsyncData(_current.copyWith(busy: false, error: _message(error)));
  }

  bool _isUserCancellation(Object error) {
    if (error is AuthClientException && error.message == 'canceled') {
      return true;
    }
    final str = error.toString().toLowerCase();
    return str.contains('popup-closed') ||
        str.contains('popup_closed') ||
        str.contains('cancelled') ||
        str.contains('canceled') ||
        str.contains('closed by user');
  }

  String _message(Object error) {
    if (error is AuthClientException) return error.message;
    return error.toString().replaceFirst('Exception: ', '');
  }
}

final authControllerProvider =
    AsyncNotifierProvider<AuthController, MarkoAuthState>(AuthController.new);
