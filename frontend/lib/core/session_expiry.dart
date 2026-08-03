import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api_client.dart';
import 'firebase_auth_client.dart';

/// Единственное место, где приложение отвечает на 401, пришедший уже после
/// загрузки страницы.
///
/// Истёкшая сессия — не «ошибка запроса». Это одно состояние приложения, у
/// которого ровно один выход: войти заново. Пока каждый вызов классифицировал
/// её сам, ответ зависел от того, какой запрос не повезло сделать первым:
/// обновление списка показывало английскую строку бэкенда, дип-линк —
/// «рекомендация не существует», экспорт — снекбар с текстом исключения, а
/// запуск расчёта предлагал нажать ту же кнопку ещё раз. Все эти ответы
/// неверны, и неверны по-разному.
///
/// Здесь 401 признаётся один раз и на всё приложение. Признание — это и есть
/// аннулирование сессии на клиенте: с этого момента ни один экран не тратит
/// мёртвый токен и не предлагает повтор, а на экране появляется единственное
/// действие, которое что-то меняет, — вход. Сам токен снимает уже [logout] за
/// этой кнопкой: делать это молча и немедленно означало бы выкинуть оператора
/// со страницы вместе с несохранённой работой и без объяснения, зачем его
/// просят войти.
class MarkoSessionExpiry extends Notifier<bool> {
  @override
  bool build() => false;

  /// Отвечает на единственный вопрос, который стоит задавать в `catch`:
  /// «это истёкшая сессия?».
  ///
  /// Если да — состояние уже поднято, и вызывающий не должен ни показывать
  /// [error], ни предлагать повтор: и то и другое было бы неправдой.
  bool classify(Object? error) {
    if (!markoIsSessionExpired(error)) return false;
    expire();
    return true;
  }

  void expire() {
    if (!state) state = true;
  }

  /// Аутентифицированный ответ дошёл: токен жив, и держать предложение войти
  /// больше не за что.
  void observeLiveSession() {
    if (state) state = false;
  }

  /// Единственное действие, которое действительно снимает истёкшую сессию:
  /// выбросить мёртвый токен, после чего роутер снова спрашивает вход.
  ///
  /// Состояние снимается только если это удалось: неснятый токен — это всё ещё
  /// истёкшая сессия, и убирать предложение войти было бы враньём.
  Future<void> signOutForNewSession() async {
    await ref.read(authClientProvider).logout();
    observeLiveSession();
  }
}

final markoSessionExpiredProvider = NotifierProvider<MarkoSessionExpiry, bool>(
  MarkoSessionExpiry.new,
);

extension MarkoSessionExpiryRef on Ref {
  bool classifySessionExpiry(Object? error) =>
      read(markoSessionExpiredProvider.notifier).classify(error);

  void observeLiveSession() =>
      read(markoSessionExpiredProvider.notifier).observeLiveSession();
}

extension MarkoSessionExpiryWidgetRef on WidgetRef {
  bool classifySessionExpiry(Object? error) =>
      read(markoSessionExpiredProvider.notifier).classify(error);
}
