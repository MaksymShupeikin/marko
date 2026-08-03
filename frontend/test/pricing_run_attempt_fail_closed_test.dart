import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/pricing/pricing_run_attempt_store.dart';
import 'package:marko_client/features/pricing/pricing_run_panel.dart';

/// Ключ идемпотентности — это обещание, а не удобство: пока он лежит в
/// хранилище, повтор после перезагрузки попадает в тот же прогон, а не
/// заказывает второй скрейпинг всего каталога.
///
/// Обещание нечем обеспечить, если хранилище недоступно — приватное окно,
/// заблокированные данные сайта, платформа без бэкенда настроек. Прежний код в
/// этом случае молча понижал идентичность до «живёт, пока жива вкладка»: старт
/// уходил, ответ терялся, вкладка перезагружалась — и повтор нёс уже другой
/// ключ. Сервер честно создавал второй платный прогон, и никто об этом не
/// узнавал до счёта.
///
/// Поэтому здесь ни одна проверка не спрашивает «удалось ли записать» после
/// запуска. Все они спрашивают, состоялся ли запуск вообще.
///
/// Хранилище в этом файле не подменяется мок-значениями намеренно:
/// `SharedPreferences.getInstance()` тогда не отвечает никогда — ровно то, что
/// делает недоступное хранилище на вебе.
void main() {
  testWidgets('a paid run does not start when its identity cannot be '
      'recorded', (tester) async {
    final backend = _RunBackend();
    await tester.pumpWidget(_app(backend));
    await _settle(tester);

    await _startAndConfirm(tester);

    expect(
      backend.startBodies,
      isEmpty,
      reason:
          'a run whose attempt cannot be written down is a run nobody can '
          'safely retry; starting it anyway spends the budget on a promise '
          'the client cannot keep',
    );
    expect(
      find.byKey(const ValueKey('pricing-run-attempt-storage-blocked')),
      findsOneWidget,
      reason: 'refusing silently is indistinguishable from a broken button',
    );
    expect(find.textContaining('TimeoutException'), findsNothing);
    expect(
      tester
          .widget<FilledButton>(find.byKey(const ValueKey('pricing-run-start')))
          .onPressed,
      isNotNull,
      reason:
          'the refusal is recoverable: storage can be re-enabled and the run '
          'confirmed again',
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('a lost response keeps its attempt when the record can still '
      'be read', (tester) async {
    final storage = _FakeStorage();
    final backend = _RunBackend(failFirstStart: true);
    await tester.pumpWidget(_app(backend, storage: storage));
    await _settle(tester);

    // Ответ потерян — но прогон на сервере мог и родиться.
    await _startAndConfirm(tester);
    expect(backend.startBodies, hasLength(1));
    expect(storage.disk[PricingRunAttemptStore.preferenceKey], isNotNull);

    // Записывать больше нельзя, но прочитать незакрытую попытку — можно, и
    // этого достаточно: новая идентичность не нужна.
    storage.writable = false;
    await _reload(tester, backend, storage: storage);
    await _startAndConfirm(tester);

    expect(backend.startBodies, hasLength(2));
    expect(
      backend.startBodies.first['idempotency_key'],
      backend.startBodies.last['idempotency_key'],
      reason: 'an unfinished attempt has to outlive the widget and the tab',
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('a lost response is never retried under a different key', (
    tester,
  ) async {
    final storage = _FakeStorage();
    final backend = _RunBackend(failFirstStart: true);
    await tester.pumpWidget(_app(backend, storage: storage));
    await _settle(tester);

    await _startAndConfirm(tester);
    expect(backend.startBodies, hasLength(1));

    // Хранилище пропало между потерянным ответом и повтором: приватное окно,
    // отозванное разрешение на данные сайта. Прочитать незакрытую попытку
    // теперь нечем — а «не знаю» и «попытки нет» ведут в разные стороны.
    storage.readable = false;
    await _reload(tester, backend, storage: storage);
    await _startAndConfirm(tester);

    expect(
      backend.startBodies,
      hasLength(1),
      reason:
          'the second confirmation could only carry a fresh key — a fresh key '
          'is a second full scrape of the catalogue, charged to the owner who '
          'asked for one run',
    );
    expect(
      find.byKey(const ValueKey('pricing-run-attempt-storage-blocked')),
      findsOneWidget,
    );
    expect(tester.takeException(), isNull);
  });

  group('a removal that did not happen', () {
    const identity = 'run:batch-1:FULL_CATALOG:scope-hash:snapshot-hash';

    test('cannot bring the spent key back', () async {
      final storage = _FakeStorage()..removable = false;
      final store = PricingRunAttemptStore(storage: storage);

      final spent = await store.reserve(identity);
      await store.release(identity);

      // Перезагрузка идёт первой: любой более ранний резерв переписал бы
      // запись и спрятал бы то, что должно быть проверено.
      expect(
        await PricingRunAttemptStore(storage: storage).reserve(identity),
        isNot(spent),
        reason:
            'a spent key that survives a reload deduplicates the next '
            'deliberate run against a finished one, and yesterday’s prices '
            'come back with no error to explain them',
      );
      expect(
        await store.reserve(identity),
        isNot(spent),
        reason:
            'the session closed the attempt; a record that outlived its own '
            'deletion is older than that decision, not newer',
      );
    });

    test(
      'does not let the next run start on a promise nothing recorded',
      () async {
        final storage = _FakeStorage();
        final store = PricingRunAttemptStore(storage: storage);
        final spent = await store.reserve(identity);

        // Ни стереть, ни переписать: хранилище отказало целиком.
        storage
          ..removable = false
          ..writable = false;
        await store.release(identity);

        expect(
          () => store.reserve(identity),
          throwsA(isA<PricingRunAttemptUnavailable>()),
          reason:
              'the only alternatives were handing back the spent key or minting '
              'one nobody wrote down; both cost the owner a run',
        );
        expect(
          storage.disk[PricingRunAttemptStore.preferenceKey],
          contains(spent),
        );
      },
    );

    test('leaves a closed record that a reload can read', () async {
      final storage = _FakeStorage()..removable = false;
      final store = PricingRunAttemptStore(storage: storage);
      final spent = await store.reserve(identity);
      await store.release(identity);

      final record = storage.disk[PricingRunAttemptStore.preferenceKey];
      expect(record, isNotNull);
      expect(
        jsonDecode(record!),
        containsPair('state', 'closed'),
        reason:
            'the durable state has to say which of the two it is; a record '
            'that only says "there was an attempt" is read as an open one',
      );
      expect(jsonDecode(record), containsPair('key', spent));
    });
  });
}

/// Хранилище, которое можно выключить по частям — так и ломается настоящее:
/// читать ещё можно, писать уже нет; удаление молча не проходит.
class _FakeStorage implements PricingRunAttemptStorage {
  final Map<String, String> disk = {};
  bool readable = true;
  bool writable = true;
  bool removable = true;

  @override
  Future<String?> read(String key) async {
    if (!readable) throw StateError('storage unavailable');
    return disk[key];
  }

  @override
  Future<void> write(String key, String value) async {
    if (!writable) throw StateError('storage unavailable');
    disk[key] = value;
  }

  @override
  Future<void> remove(String key) async {
    if (!removable) throw StateError('storage unavailable');
    disk.remove(key);
  }
}

Widget _app(_RunBackend backend, {PricingRunAttemptStorage? storage}) {
  return ProviderScope(
    overrides: [
      apiClientProvider.overrideWithValue(
        ApiClient(client: backend.client, baseUrl: 'https://api.example.test'),
      ),
      if (storage != null)
        pricingRunAttemptStoreProvider.overrideWithValue(
          PricingRunAttemptStore(storage: storage),
        ),
    ],
    child: MaterialApp(
      theme: AppTheme.light,
      locale: const Locale('ru'),
      supportedLocales: const [Locale('ru'), Locale('uk')],
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
      home: Scaffold(
        body: Center(
          child: PricingRunPanel(
            canAdministerWorkspace: true,
            onRunFinished: () {},
          ),
        ),
      ),
    ),
  );
}

/// Перезагрузка вкладки: дерево и контейнер провайдеров исчезают, остаётся
/// только то, что было записано в хранилище, — то есть ничего.
Future<void> _reload(
  WidgetTester tester,
  _RunBackend backend, {
  PricingRunAttemptStorage? storage,
}) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await tester.pump();
  await tester.pumpWidget(_app(backend, storage: storage));
  await _settle(tester);
}

Future<void> _startAndConfirm(WidgetTester tester) async {
  await tester.tap(find.byKey(const ValueKey('pricing-run-start')));
  await _settle(tester);
  await tester.tap(find.text('Запустить').last);
  // Ограниченные помпы: кнопка держит спиннер, пока запрос в полёте, и
  // `pumpAndSettle` гонялся бы за анимацией. Пауза должна перекрыть бюджет
  // хранилища с запасом — иначе «старт не ушёл» означало бы всего лишь «мы не
  // дождались», а это не отказ, а таймаут теста.
  await tester.pump();
  for (var i = 0; i < 6; i += 1) {
    await tester.pump(const Duration(seconds: 5));
    await _settle(tester);
  }
}

Future<void> _settle(WidgetTester tester) async {
  await tester.pump();
  for (var i = 0; i < 12; i += 1) {
    await tester.pump(const Duration(milliseconds: 50));
  }
}

class _RunBackend {
  _RunBackend({this.failFirstStart = false});

  final bool failFirstStart;
  final List<Map<String, dynamic>> startBodies = [];

  http.Client get client => MockClient((request) async {
    final path = request.url.path;
    if (request.method == 'GET' && path == '/api/v1/pricing/runs') {
      return _jsonResponse({
        'items': <Object>[],
        'total': 0,
        'limit': 25,
        'offset': 0,
      });
    }
    if (request.method == 'GET' && path == '/api/v1/catalog/imports') {
      return _jsonResponse(_importPage());
    }
    if (request.method == 'POST' && path == '/api/v1/pricing/runs/preview') {
      return _jsonResponse(_previewJson());
    }
    if (request.method == 'POST' && path == '/api/v1/pricing/runs') {
      startBodies.add(jsonDecode(request.body) as Map<String, dynamic>);
      if (failFirstStart && startBodies.length == 1) {
        return _jsonResponse({
          'detail': 'Pricing worker temporarily unavailable',
        }, statusCode: 503);
      }
      return _jsonResponse(_runJson('completed'), statusCode: 202);
    }
    if (request.method == 'GET' && path == '/api/v1/pricing/runs/run-1') {
      return _jsonResponse(_runJson('completed'));
    }
    return http.Response('not found', 404);
  });
}

http.Response _jsonResponse(Object payload, {int statusCode = 200}) {
  return http.Response(
    jsonEncode(payload),
    statusCode,
    headers: {'content-type': 'application/json'},
  );
}

Map<String, dynamic> _importPage() => {
  'items': [
    {
      'id': 'batch-1',
      'filename': 'catalog.xlsx',
      'status': 'completed',
      'column_mapping': {'sku': 'SKU'},
      'total_rows': 10,
      'imported_rows': 10,
      'rejected_rows': 0,
      'error_log': <Object>[],
      'created_at': '2026-07-30T04:00:00Z',
    },
  ],
  'total': 1,
  'limit': 100,
  'offset': 0,
};

Map<String, dynamic> _runJson(String status) => {
  'id': 'run-1',
  'import_batch_id': 'batch-1',
  'status': status,
  'coefficient_model': 'shrinkage',
  'coefficient_version': null,
  'calibration_dataset_hash': null,
  'calibration_accounting': <String, dynamic>{},
  'total_items': 10,
  'completed_items': 10,
  'failed_items': 0,
  'manual_review_items': 0,
  'cancel_requested': false,
  'error': null,
  'created_at': '2026-07-30T04:00:00Z',
};

Map<String, dynamic> _previewJson() => {
  'scope_contract_version': 'v1',
  'import_batch_id': 'batch-1',
  'scope_mode': 'FULL_CATALOG',
  'policy_version': 'test-v1',
  'catalog_snapshot_hash': 'a' * 64,
  'scope_hash': 'b' * 64,
  'preview_token': 'mrp1_testtoken0000000000000000000000000000',
  'requires_full_catalog_confirmation': true,
  'estimate': {
    'requested_items': 10,
    'eligible_items': 10,
    'excluded_items': 0,
    'unique_scrape_inputs': 10,
    'duplicate_items': 0,
    'worst_case_duration_seconds': 120,
  },
  'exclusions': <Map<String, dynamic>>[],
  'exclusions_truncated': false,
  'scope_manifest': <String, dynamic>{},
};
