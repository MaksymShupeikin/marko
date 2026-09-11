import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/repricing/repricing_api.dart';
import 'package:marko_client/features/repricing/repricing_page.dart';
import 'package:marko_client/features/repricing/widgets/reprice_card.dart';
import 'package:toastification/toastification.dart';

/// A repricing backend with one finished run and three rows — one of each
/// outcome, because the whole point is that they never look alike.
class _Backend {
  _Backend({
    this.matching = 120,
    this.remaining = 40,
    this.checksLeft,
    this.catalogIsCurrent = true,
    this.signatureChanged = false,
    this.runs = 1,
  });

  final int matching;
  final int remaining;
  final int? checksLeft;
  final bool catalogIsCurrent;
  final bool signatureChanged;
  final int runs;

  /// Режим, який востаннє просив клієнт, — так видно, що межа повзунка
  /// перерахувалась саме через зміну режиму.
  String lastPreviewMode = 'fresh';

  /// Скільки разів клієнт спробував запустити прогін.
  int startAttempts = 0;

  /// Скільки разів просили перенести покриття.
  int carryOvers = 0;

  /// Які саме прогони вивантажували.
  final List<String> exported = [];

  Map<String, dynamic> get _preview => {
    'catalog': {
      'signature': 'abcdef1234567890',
      'item_count': matching,
      'store_ids': ['store-1'],
    },
    'matching': matching,
    'covered': matching - remaining,
    'remaining': lastPreviewMode == 'resume' ? remaining : matching,
    'checks_left': checksLeft,
    'last_run_signature': 'abcdef1234567890',
    'signature_changed': signatureChanged,
  };

  Map<String, dynamic> _run(String id, {String status = 'completed'}) => {
    'id': id,
    'sync_run_id': 'sync-$id',
    'scope': 'partial',
    'mode': 'fresh',
    'policy': 'balanced',
    'engine': 'legacy_min_minus',
    'requested_count': 3,
    'catalog': {
      'signature': 'abcdef1234567890',
      'item_count': matching,
      'store_ids': ['store-1'],
    },
    'catalog_is_current': catalogIsCurrent,
    'status': status,
    'progress_current': 3,
    'progress_total': 3,
    'error': null,
    'changed_count': 1,
    'unchanged_count': 1,
    'skipped_count': 1,
    'failed_count': 0,
    'created_at': '2026-09-11T09:15:00Z',
    'started_at': '2026-09-11T09:15:01Z',
    'finished_at': '2026-09-11T09:16:00Z',
  };

  static Map<String, dynamic> _item({
    required String id,
    required String name,
    required String? outcome,
    String? reason,
    num? oldPrice,
    num? newPrice,
    num? deltaPct,
    bool priceChangedSince = false,
  }) => {
    'listing_id': id,
    'position': 0,
    'name': name,
    'sku': 'SKU-$id',
    'brand': 'KEMP',
    'store_name': 'Автозапчастини',
    'image_url': null,
    'url': 'https://x.prom.ua/$id.html',
    'currency': 'UAH',
    'status': 'done',
    'outcome': outcome,
    'reason': reason,
    'old_price': oldPrice,
    'new_price': newPrice,
    'delta_abs': null,
    'delta_pct': deltaPct,
    'price_changed_since': priceChangedSince,
    'zone': 'premium',
    'tier': null,
    'method': 'legacy_min_minus',
    'confidence': null,
    'offers_total': 12,
    'evidence': null,
    'dismissed': false,
  };

  ApiClient client() {
    return ApiClient(
      client: MockClient((request) async {
        final path = request.url.path;
        String body;
        if (path == '/api/v1/reprice/reconciliation') {
          body = jsonEncode({
            'signature_changed': signatureChanged,
            'previous_signature': 'old12345',
            'kept': 46012,
            'gone': 87,
            'fresh': 340,
          });
        } else if (path == '/api/v1/reprice/carry-over') {
          carryOvers += 1;
          body = jsonEncode(_run('run-carry'));
        } else if (path == '/api/v1/reprice/preview') {
          final payload = jsonDecode(request.body) as Map<String, dynamic>;
          lastPreviewMode = payload['mode'] as String? ?? 'fresh';
          body = jsonEncode(_preview);
        } else if (path == '/api/v1/reprice/runs') {
          if (request.method == 'POST') {
            startAttempts += 1;
            return http.Response(
              jsonEncode(_run('run-new', status: 'running')),
              201,
              headers: {'content-type': 'application/json; charset=utf-8'},
            );
          }
          body = jsonEncode({
            'items': [for (var i = 0; i < runs; i++) _run('run-$i')],
            'total': runs,
            'limit': 20,
            'offset': 0,
          });
        } else if (path.endsWith('/export.xlsx')) {
          exported.add(path.split('/')[5]);
          return http.Response.bytes([80, 75, 3, 4], 200);
        } else if (path.endsWith('/items')) {
          body = jsonEncode({
            'items': [
              _item(
                id: 'a',
                name: 'Амортизатор передній',
                outcome: 'changed',
                oldPrice: 1950,
                newPrice: 1780,
                deltaPct: -8.7,
              ),
              _item(
                id: 'b',
                name: 'Фільтр масляний',
                outcome: 'unchanged',
                oldPrice: 300,
                newPrice: 300,
              ),
              _item(
                id: 'c',
                name: 'Прокладка колектора',
                outcome: 'no_recommendation',
                reason: 'Тонкий ринок: менше трьох підтверджених цін',
                oldPrice: 500,
              ),
            ],
            'total': 3,
            'limit': 60,
            'offset': 0,
          });
        } else if (path.startsWith('/api/v1/reprice/runs/')) {
          body = jsonEncode(_run('run-0'));
        } else {
          body = '{}';
        }
        return http.Response(
          body,
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }),
      baseUrl: 'http://api.test',
    );
  }
}

/// Тости живуть у кореневому оверлеї й переживають дію, що їх підняла:
/// поза вебом вивантаження показує попередження, і його таймер треба зняти.
Future<void> _clearToasts(WidgetTester tester) async {
  toastification.dismissAll(delayForAnimation: false);
  await tester.pump(const Duration(milliseconds: 700));
  await tester.pumpAndSettle();
}

Widget _app(ApiClient client) => ProviderScope(
  overrides: [repricingApiProvider.overrideWithValue(RepricingApi(client))],
  child: MaterialApp(theme: AppTheme.light, home: const RepricingPage()),
);

void main() {
  setUp(() {
    final view = TestWidgetsFlutterBinding.ensureInitialized()
        .platformDispatcher
        .views
        .first;
    view.physicalSize = const Size(1400, 2400);
    view.devicePixelRatio = 1;
  });

  tearDown(() {
    final view = TestWidgetsFlutterBinding.ensureInitialized()
        .platformDispatcher
        .views
        .first;
    view.resetPhysicalSize();
    view.resetDevicePixelRatio();
  });

  testWidgets('the three outcomes never look like one another', (tester) async {
    await tester.pumpWidget(_app(_Backend().client()));
    await tester.pumpAndSettle();

    expect(find.byType(RepriceCard), findsNWidgets(3));
    // Змінено — стара й нова ціна поруч.
    expect(find.textContaining('1 950'), findsOneWidget);
    expect(find.textContaining('1 780'), findsOneWidget);
    expect(find.textContaining('8.7%'), findsOneWidget);
    // Без змін — окреме твердження, а не тиша.
    expect(find.text('Без змін — ціна вже відповідає ринку'), findsOneWidget);
    // Не пораховано — завжди з причиною.
    expect(find.text('Не пораховано'), findsOneWidget);
    expect(
      find.text('Тонкий ринок: менше трьох підтверджених цін'),
      findsOneWidget,
    );
  });

  testWidgets('the slider bound follows the catalog, not a guess', (
    tester,
  ) async {
    await tester.pumpWidget(
      _app(_Backend(matching: 120, remaining: 40).client()),
    );
    await tester.pumpAndSettle();

    expect(find.text('120 з 120'), findsOneWidget);

    await tester.tap(find.text('Продовжити'));
    await tester.pumpAndSettle();

    // Межа повзунка стала «скільки лишилось», а не «скільки всього».
    expect(find.text('40 з 40'), findsOneWidget);
    expect(find.text('Ще не перевірено: 40'), findsOneWidget);
  });

  testWidgets('a run is stamped with its date and its catalog', (tester) async {
    await tester.pumpWidget(_app(_Backend(catalogIsCurrent: false).client()));
    await tester.pumpAndSettle();

    expect(find.textContaining('каталог abcdef12'), findsOneWidget);
    expect(find.textContaining('каталог відтоді змінився'), findsOneWidget);
  });

  testWidgets('a short check limit stops the run before it starts', (
    tester,
  ) async {
    final backend = _Backend(matching: 500, checksLeft: 30);
    await tester.pumpWidget(_app(backend.client()));
    await tester.pumpAndSettle();

    expect(
      find.textContaining('Ліміту перевірок не вистачить на 500 товарів'),
      findsOneWidget,
    );

    await tester.tap(find.text('Запустити'));
    await tester.pumpAndSettle();

    // Прогін, що впаде на 31-му товарі, краще не починати зовсім.
    expect(backend.startAttempts, 0);
  });

  testWidgets('a changed catalog is announced with what it costs', (
    tester,
  ) async {
    final backend = _Backend(signatureChanged: true);
    await tester.pumpWidget(_app(backend.client()));
    await tester.pumpAndSettle();

    expect(
      find.text('Склад каталогу змінився з часу останнього прогону'),
      findsOneWidget,
    );
    expect(
      find.textContaining('46012 порахованих товарів на місці'),
      findsOneWidget,
    );
    expect(find.textContaining('87 зникли'), findsOneWidget);
    expect(find.textContaining('340 ще не рахували'), findsOneWidget);

    // Перенесення покриття — щоб «продовжити» не починало з початку.
    await tester.tap(find.text('Перенести покриття'));
    await tester.pumpAndSettle();
    expect(backend.carryOvers, 1);
  });

  testWidgets('an unchanged catalog says nothing at all', (tester) async {
    await tester.pumpWidget(_app(_Backend().client()));
    await tester.pumpAndSettle();

    expect(
      find.text('Склад каталогу змінився з часу останнього прогону'),
      findsNothing,
    );
  });

  testWidgets('history lists past runs and hands over their sheets', (
    tester,
  ) async {
    final backend = _Backend(runs: 2);
    await tester.pumpWidget(_app(backend.client()));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Історія'));
    await tester.pumpAndSettle();

    expect(find.text('Історія прогонів'), findsOneWidget);
    expect(
      find.textContaining('змінено 1 · без змін 1 · не пораховано 1'),
      findsNWidgets(2),
    );

    // Вивантажити минулий прогін можна прямо з рядка, не відкриваючи його.
    await tester.tap(find.byTooltip('Вивантажити в Excel').first);
    await tester.pumpAndSettle();
    expect(backend.exported, ['run-0']);
    await _clearToasts(tester);
  });
}
