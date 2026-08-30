import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/products/products_api.dart';
import 'package:marko_client/features/products/products_page.dart';
import 'package:marko_client/features/products/widgets/product_card.dart';
import 'package:marko_client/features/products/widgets/source_panel.dart';

/// A catalog that starts empty and grows once the sync reports progress, plus
/// a queue that runs one job, then empties.
class _Backend {
  _Backend({this.queues, List<Map<String, dynamic>>? jobStates})
    : _jobStates = jobStates ?? [run(status: 'completed', current: 4)];

  int products = 0;

  /// Черги, які віддає /jobs/active по одній на кожен опит.
  final List<List<Map<String, dynamic>>>? queues;
  final List<Map<String, dynamic>> _jobStates;

  static Map<String, dynamic> run({
    String id = 'run-1',
    String status = 'running',
    int current = 2,
    int? total = 4,
    String? storeName,
  }) => {
    'id': id,
    'workspace_id': 'w1',
    'store_id': 's1',
    'kind': 'catalog_import',
    'status': status,
    'progress_current': current,
    'progress_total': total,
    'error': null,
    'started_at': null,
    'finished_at': null,
    'created_at': '2026-08-28T10:00:00Z',
    'updated_at': '2026-08-28T10:00:00Z',
    'store_name': storeName,
    'store_logo_url': null,
  };

  // Перший опит — на старті сторінки: черга ще порожня.
  late final List<List<Map<String, dynamic>>> _queue =
      queues ??
      [
        const [],
        [run()],
        const [],
      ];

  ApiClient client() {
    return ApiClient(
      client: MockClient((request) async {
        final body = switch (request.url.path) {
          '/api/v1/products' => jsonEncode({
            'items': [
              for (var i = 0; i < products; i++)
                {
                  'id': 'p$i',
                  'name': 'Товар $i',
                  'url': 'https://x.prom.ua/p$i.html',
                  'sku': 'SKU-$i',
                  'brand': 'KEMP',
                  'currency': 'UAH',
                  'current_price': 100,
                  'is_available': true,
                  'image_url': null,
                  'oem_numbers': const [],
                  'can_manage': true,
                },
            ],
            'total': products,
            'limit': 60,
            'offset': 0,
          }),
          '/api/v1/stores' => jsonEncode({
            'store_id': 's1',
            'sync_run_id': 'run-1',
            'status': 'queued',
          }),
          '/api/v1/jobs/active' => () {
            final queue = _queue.length > 1 ? _queue.removeAt(0) : _queue.first;
            if (queue.isNotEmpty) products += 2;
            return jsonEncode(queue);
          }(),
          // Підсумок запуску, якого вже нема в активних: останні товари доїхали.
          '/api/v1/jobs/run-1' => () {
            final job = _jobStates.length > 1
                ? _jobStates.removeAt(0)
                : _jobStates.first;
            if (job['status'] == 'completed') products += 2;
            return jsonEncode(job);
          }(),
          _ => '{}',
        };
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

Widget _app(ApiClient client) => ProviderScope(
  overrides: [productsApiProvider.overrideWithValue(ProductsApi(client))],
  child: MaterialApp(
    theme: AppTheme.light,
    home: const Scaffold(body: ProductsPage()),
  ),
);

void main() {
  setUp(() {
    final view = TestWidgetsFlutterBinding.ensureInitialized()
        .platformDispatcher
        .views
        .first;
    view.physicalSize = const Size(1400, 1800);
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

  testWidgets('a running sync shows the island, streams products, then goes', (
    tester,
  ) async {
    await tester.pumpWidget(_app(_Backend().client()));
    await tester.pumpAndSettle();

    // Порожній каталог — онбординг, ані капсули, ані скелетонів.
    expect(find.text('Додайте товари з XLSX-файлу'), findsOneWidget);
    expect(find.byType(ProductCardSkeleton), findsNothing);

    await tester.enterText(
      find.byType(TextField).first,
      'https://prom.ua/c1-shop.html',
    );
    await tester.tap(find.text('Імпортувати каталог').first);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));

    // Онбординг поступився каталогу: капсула зверху, привиди в сітці.
    expect(find.text('Синхронізація'), findsOneWidget);
    expect(find.text('Додайте товари з XLSX-файлу'), findsNothing);
    expect(find.byType(ProductCardSkeleton), findsWidgets);
    expect(find.text('Товар 0'), findsOneWidget);

    // Другий опит завершує роботу: підсумок, потім капсула зникає сама.
    await tester.pump(const Duration(seconds: 2));
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.text('Каталог оновлено'), findsOneWidget);
    expect(find.byType(ProductCardSkeleton), findsNothing);
    expect(find.text('Товар 3'), findsOneWidget);

    await tester.pump(const Duration(seconds: 5));
    await tester.pumpAndSettle();
    expect(find.text('Каталог оновлено'), findsNothing);
  });

  testWidgets('the sync panel no longer duplicates the progress inline', (
    tester,
  ) async {
    await tester.pumpWidget(_app(_Backend().client()));
    await tester.pumpAndSettle();

    expect(find.byType(SourcePanel), findsOneWidget);
    expect(find.textContaining('Імпорт каталогу:'), findsNothing);
  });

  testWidgets('a Prom job stays visible while the active queue catches up', (
    tester,
  ) async {
    final backend = _Backend(
      queues: [
        const [],
        const [],
        [_Backend.run(current: 1)],
        const [],
      ],
      jobStates: [
        _Backend.run(status: 'queued', current: 0, total: null),
        _Backend.run(status: 'completed', current: 4),
      ],
    );
    await tester.pumpWidget(_app(backend.client()));
    await tester.pumpAndSettle();

    await tester.enterText(
      find.byType(TextField).first,
      'https://prom.ua/c1-shop.html',
    );
    await tester.tap(find.text('Імпортувати каталог').first);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));

    // POST already returned the job, while /jobs/active still answers [].
    expect(find.text('Синхронізація'), findsOneWidget);
    expect(find.byType(ProductCardSkeleton), findsWidgets);

    await tester.pump(const Duration(seconds: 2));
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.text('Синхронізація'), findsOneWidget);
    expect(find.text('Товар 0'), findsOneWidget);

    await tester.pump(const Duration(seconds: 2));
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.text('Каталог оновлено'), findsOneWidget);

    await tester.pump(const Duration(seconds: 5));
    await tester.pumpAndSettle();
  });

  testWidgets('the queue stacks stores and hides the tail behind a toggle', (
    tester,
  ) async {
    final queue = [
      _Backend.run(id: 'run-1', storeName: 'kemp'),
      _Backend.run(
        id: 'run-2',
        status: 'queued',
        current: 0,
        total: null,
        storeName: 'avtobust',
      ),
      _Backend.run(
        id: 'run-3',
        status: 'queued',
        current: 0,
        total: null,
        storeName: 'profparts',
      ),
      _Backend.run(
        id: 'run-4',
        status: 'queued',
        current: 0,
        total: null,
        storeName: 'parts-avto',
      ),
    ];
    await tester.pumpWidget(
      _app(_Backend(queues: [queue, queue, queue, const []]).client()),
    );
    // Промінь капсули крутиться без упину — settle тут не дочекається.
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));

    // Видно активний магазин і один наступний; решта — за кнопкою.
    expect(find.text('kemp'), findsOneWidget);
    expect(find.text('avtobust'), findsOneWidget);
    expect(find.text('profparts'), findsNothing);
    expect(find.text('Ще 2 магазини в черзі'), findsOneWidget);

    await tester.tap(find.text('Ще 2 магазини в черзі'));
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));

    expect(find.text('profparts'), findsOneWidget);
    expect(find.text('parts-avto'), findsOneWidget);
    expect(find.text('Згорнути чергу'), findsOneWidget);

    await tester.tap(find.text('Згорнути чергу'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 600));
    expect(find.text('parts-avto'), findsNothing);

    // Даємо черзі спорожніти, інакше опитування переживе сам тест.
    await tester.pump(const Duration(seconds: 2));
    await tester.pump(const Duration(milliseconds: 400));
    await tester.pump(const Duration(seconds: 5));
    await tester.pumpAndSettle();
  });
}
