import 'dart:convert';
import 'dart:math';

import 'package:crypto/crypto.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Одна попытка запуска расчёта: во что владелец уже упёрся кнопкой и чем это
/// закончилось на сервере.
class PricingRunAttempt {
  const PricingRunAttempt({
    required this.identity,
    required this.key,
    this.isClosed = false,
  });

  final String identity;
  final String key;

  /// Попытка закрыта успешным стартом. Её ключ потрачен: сервер уже связал с
  /// ним прогон, и следующее подтверждение обязано принести другой.
  final bool isClosed;
}

/// Долговечную идентичность попытки не удалось ни прочитать, ни записать.
///
/// Это не «ошибка сохранения настроек», после которой можно продолжать: без
/// записи повтор после перезагрузки не отличит себя от нового заказа.
class PricingRunAttemptUnavailable implements Exception {
  const PricingRunAttemptUnavailable(this.stage, this.cause);

  final PricingRunAttemptStage stage;
  final Object? cause;

  @override
  String toString() => 'PricingRunAttemptUnavailable(${stage.name}): $cause';
}

enum PricingRunAttemptStage { read, write }

/// Долговечная часть попытки — ровно одна запись, которую надо уметь прочитать,
/// переписать и стереть.
///
/// Границей она стала потому, что отказ хранилища здесь меняет решение
/// («запускать ли платный прогон»), а не оформление. Такое решение нельзя
/// проверять только на живом браузере в приватном окне.
abstract class PricingRunAttemptStorage {
  /// `null` — записи нет. Невозможность прочитать — исключение, а не `null`:
  /// «не знаю» и «нет незакрытой попытки» ведут к противоположным действиям.
  Future<String?> read(String key);

  Future<void> write(String key, String value);

  Future<void> remove(String key);
}

/// Реализация по умолчанию поверх настроек приложения.
class SharedPreferencesAttemptStorage implements PricingRunAttemptStorage {
  const SharedPreferencesAttemptStorage({
    this.budget = const Duration(seconds: 3),
  });

  /// Хранилище на вебе отвечает за миллисекунды. Если оно не ответило совсем —
  /// приватное окно, заблокированные данные сайта, платформа без бэкенда
  /// настроек, — ждать дольше нечего: ответ не изменится.
  final Duration budget;

  Future<SharedPreferences> _preferences() =>
      SharedPreferences.getInstance().timeout(budget);

  @override
  Future<String?> read(String key) async =>
      (await _preferences()).getString(key);

  @override
  Future<void> write(String key, String value) async {
    final preferences = await _preferences();
    final stored = await preferences.setString(key, value).timeout(budget);
    if (!stored) throw StateError('preferences rejected $key');
  }

  @override
  Future<void> remove(String key) async {
    final preferences = await _preferences();
    final removed = await preferences.remove(key).timeout(budget);
    if (!removed) throw StateError('preferences kept $key');
  }
}

/// Кто такая «та же попытка» — вопрос, переживающий и виджет, и вкладку.
///
/// Ключ идемпотентности отвечает именно на него, а не на «та же область?»:
/// область повторного прогона совпадает по построению. Счётчик в состоянии
/// виджета выглядит как ответ ровно до первой перезагрузки — после неё он снова
/// равен единице, второе осознанное подтверждение приносит уже потраченный
/// ключ, и сервер отдаёт старый, давно завершённый прогон. Ошибки нет, объяснения
/// вчерашним ценам — тоже.
///
/// Поэтому идентичность попытки — случайная и записанная: пока попытка не
/// закрыта успехом, её ключ лежит в хранилище и переживает перезагрузку
/// (потерянный ответ мог оставить после себя настоящий прогон, и повтор обязан
/// попасть в него); как только старт удался, запись удаляется, и следующее
/// подтверждение получает новый случайный ключ.
///
/// Если записать её негде, [reserve] отказывает. Прежде на этом месте была
/// «попытка на время сессии»: старт уходил, ответ терялся, вкладка
/// перезагружалась — и повтор нёс другой ключ, то есть заказывал второй платный
/// скрейпинг того же каталога. Молчаливое понижение гарантии здесь дороже
/// отказа, потому что отказ виден, а лишний прогон — только в счёте.
class PricingRunAttemptStore {
  PricingRunAttemptStore({Random? random, PricingRunAttemptStorage? storage})
    : _random = random ?? Random.secure(),
      _storage = storage ?? const SharedPreferencesAttemptStorage();

  /// Единственная незакрытая попытка на приложение: панель не может вести две
  /// сразу, а подтверждение другой области отменяет предыдущую.
  static const preferenceKey = 'marko.pricing.pending_run_attempt';

  final Random _random;
  final PricingRunAttemptStorage _storage;

  /// Что эта сессия последний раз решила о незакрытой попытке; `null` при
  /// [_decided] значит «попытка закрыта».
  ///
  /// Решение сессии всегда новее записи: оно принято уже после того, как запись
  /// была прочитана. Поэтому конфликт разрешается в одну сторону и без
  /// оговорок — иначе неудавшееся удаление воскрешало бы потраченный ключ и
  /// склеивало следующий осознанный прогон с завершённым.
  PricingRunAttempt? _decision;
  bool _decided = false;

  /// Ключ текущей попытки для [identity], новый и случайный, если незакрытой
  /// попытки с такой областью нет.
  ///
  /// Бросает [PricingRunAttemptUnavailable], если долговечную запись нельзя
  /// прочитать или обновить. Вызывающий обязан не запускать прогон.
  Future<String> reserve(String identity) async {
    final outstanding = await _outstanding();
    if (outstanding != null &&
        outstanding.identity == identity &&
        !outstanding.isClosed) {
      _remember(outstanding);
      return outstanding.key;
    }
    final attempt = PricingRunAttempt(identity: identity, key: _mint(identity));
    await _persist(attempt);
    _remember(attempt);
    return attempt.key;
  }

  /// Попытка закрыта. Следующее подтверждение той же области — уже другой
  /// осознанный прогон, и сервер обязан его создать.
  ///
  /// Не бросает: старт уже состоялся, и отказывать задним числом нечему.
  Future<void> release(String identity) async {
    final outstanding = _decided ? _decision : null;
    if (_decided && (outstanding == null || outstanding.identity != identity)) {
      return;
    }
    // Решение сессии записывается первым и с этого момента перекрывает любую
    // запись: даже если стереть её не удастся, потраченный ключ больше не
    // вернётся из хранилища.
    _decided = true;
    _decision = null;
    try {
      await _storage.remove(preferenceKey);
      return;
    } catch (_) {
      // Удаление не прошло. Запись всё ещё называет потраченный ключ
      // незакрытой попыткой и переживёт перезагрузку, поэтому надгробие —
      // вторая, более слабая попытка сделать долговечное состояние
      // однозначным.
    }
    try {
      await _storage.write(
        preferenceKey,
        _encode(
          PricingRunAttempt(
            identity: identity,
            key: outstanding?.key ?? '',
            isClosed: true,
          ),
        ),
      );
    } catch (_) {
      // Долговечное состояние осталось несогласованным. Следующий [reserve] не
      // сможет записать новую попытку по той же причине и откажет в старте —
      // это и есть отказ в закрытую сторону.
    }
  }

  /// `run:<отпечаток области>:<случайность>`, 61 символ — внутри контракта в
  /// 8..160. Отпечаток оставлен для читаемости логов и как страховка: даже
  /// повторись случайность, попытка над другой областью не склеится с этой.
  String _mint(String identity) {
    final fingerprint = sha256
        .convert(utf8.encode(identity))
        .toString()
        .substring(0, 24);
    final entropy = List<int>.generate(
      16,
      (_) => _random.nextInt(256),
    ).map((byte) => byte.toRadixString(16).padLeft(2, '0')).join();
    return 'run:$fingerprint:$entropy';
  }

  void _remember(PricingRunAttempt attempt) {
    _decided = true;
    _decision = attempt;
  }

  /// Незакрытая попытка, о которой знает это приложение.
  ///
  /// Хранилище спрашивается только пока сессия ничего не решала — то есть сразу
  /// после перезагрузки. Дальше её решение и есть истина: ничто другое эту
  /// запись не пишет, а прочитать можно только то, что она сама оставила или не
  /// смогла стереть.
  Future<PricingRunAttempt?> _outstanding() async {
    if (_decided) return _decision;
    final String? raw;
    try {
      raw = await _storage.read(preferenceKey);
    } catch (error) {
      throw PricingRunAttemptUnavailable(PricingRunAttemptStage.read, error);
    }
    return _decode(raw);
  }

  Future<void> _persist(PricingRunAttempt attempt) async {
    try {
      await _storage.write(preferenceKey, _encode(attempt));
    } catch (error) {
      throw PricingRunAttemptUnavailable(PricingRunAttemptStage.write, error);
    }
  }

  String _encode(PricingRunAttempt attempt) => jsonEncode({
    'identity': attempt.identity,
    'key': attempt.key,
    'state': attempt.isClosed ? 'closed' : 'open',
  });

  PricingRunAttempt? _decode(String? raw) {
    if (raw == null) return null;
    try {
      final payload = jsonDecode(raw);
      if (payload is! Map) return null;
      final identity = payload['identity'];
      final key = payload['key'];
      if (identity is! String) return null;
      // Надгробие описывает закрытую попытку: ключ в нём диагностический, и
      // требовать от него длины бессмысленно.
      if (payload['state'] == 'closed') {
        return PricingRunAttempt(
          identity: identity,
          key: key is String ? key : '',
          isClosed: true,
        );
      }
      // Запись без `state` — формат прошлой версии, и означал он именно
      // незакрытую попытку.
      if (key is! String || key.length < 8) return null;
      return PricingRunAttempt(identity: identity, key: key);
    } on FormatException {
      // A corrupted record is not an attempt; minting a new one is the safe
      // direction, because it can only ever create a run the operator asked
      // for.
      return null;
    }
  }
}

final pricingRunAttemptStoreProvider = Provider<PricingRunAttemptStore>(
  (ref) => PricingRunAttemptStore(),
);
