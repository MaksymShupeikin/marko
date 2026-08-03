import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:marko_client/core/api_client.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/catalog/catalog_import_dialog.dart';
import 'package:marko_client/features/pricing/discovery_funnel_panel.dart';
import 'package:marko_client/features/pricing/pricing_models.dart';
import 'package:marko_client/features/pricing/pricing_reason_labels.dart';
import 'package:marko_client/features/pricing/pricing_run_panel.dart';
import 'package:marko_client/features/pricing/recommendation_export_button.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  // An outstanding run attempt outlives the widget, so the run panel now needs
  // the platform storage it is written to.
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets(
    'catalog import requires explicit sheet and exposes partial row reasons',
    (tester) async {
      var imported = 0;
      var previewRequests = 0;
      var uploadRequests = 0;
      final client = MockClient((request) async {
        if (request.url.path.endsWith('/imports/preview')) {
          previewRequests += 1;
          return _jsonResponse(_previewJson());
        }
        if (request.url.path.endsWith('/imports')) {
          uploadRequests += 1;
          return _jsonResponse(_importJson(status: 'partial'));
        }
        return http.Response('not found', 404);
      });

      await tester.pumpWidget(
        _app(
          client: client,
          child: CatalogImportDialog(
            canAdministerWorkspace: true,
            onImported: () => imported += 1,
            pickFile: () async => PickedCatalogFile(
              name: 'catalog.xlsx',
              bytes: Uint8List.fromList([1, 2, 3]),
            ),
          ),
        ),
      );

      await tester.tap(find.byKey(const ValueKey('catalog-import-pick-file')));
      await tester.pumpAndSettle();

      expect(previewRequests, 1);
      expect(find.text('Лист каталога'), findsOneWidget);
      expect(
        tester
            .widget<FilledButton>(
              find.byKey(const ValueKey('catalog-import-submit')),
            )
            .onPressed,
        isNull,
        reason: 'the service must not guess between two catalog-like sheets',
      );

      await tester.tap(find.byKey(const ValueKey('catalog-import-sheet')));
      await tester.pumpAndSettle();
      await tester.tap(find.textContaining('Export Products Sheet').last);
      await tester.pumpAndSettle();

      expect(
        tester
            .widget<FilledButton>(
              find.byKey(const ValueKey('catalog-import-submit')),
            )
            .onPressed,
        isNotNull,
      );
      await tester.ensureVisible(
        find.byKey(const ValueKey('catalog-import-submit')),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const ValueKey('catalog-import-submit')));
      await tester.pumpAndSettle();

      expect(uploadRequests, 1);
      expect(imported, 1);
      expect(find.text('Каталог импортирован частично'), findsOneWidget);
      expect(find.textContaining('Записано 4647 из 4901'), findsOneWidget);
      expect(
        find.textContaining('Коллизия нормализованного OE'),
        findsOneWidget,
      );
      expect(find.textContaining('NORMALIZED_OE_COLLISION'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('catalog import has a dedicated member-forbidden state', (
    tester,
  ) async {
    await tester.pumpWidget(
      _app(
        client: MockClient((_) async => http.Response('unexpected', 500)),
        child: CatalogImportDialog(
          canAdministerWorkspace: false,
          onImported: () {},
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Импорт доступен администратору'), findsOneWidget);
    expect(
      find.byKey(const ValueKey('catalog-import-pick-file')),
      findsNothing,
    );
  });

  testWidgets('catalog import rejects a non-xlsx file before the API call', (
    tester,
  ) async {
    var requests = 0;
    await tester.pumpWidget(
      _app(
        client: MockClient((_) async {
          requests += 1;
          return http.Response('unexpected', 500);
        }),
        child: CatalogImportDialog(
          canAdministerWorkspace: true,
          onImported: () {},
          pickFile: () async => PickedCatalogFile(
            name: 'catalog.csv',
            bytes: Uint8List.fromList([1]),
          ),
        ),
      ),
    );
    await tester.tap(find.byKey(const ValueKey('catalog-import-pick-file')));
    await tester.pumpAndSettle();

    expect(find.text('Выберите файл формата .xlsx.'), findsOneWidget);
    expect(requests, 0);
  });

  test(
    'pricing polling uses exponential delay and stops at terminal status',
    () async {
      var fetches = 0;
      final waits = <Duration>[];
      final updates = <String>[];
      final result = await pollPricingRun(
        fetch: (_) async {
          fetches += 1;
          return _run(fetches == 3 ? 'completed' : 'running');
        },
        runId: 'run-1',
        onUpdate: (run) => updates.add(run.status),
        initialDelay: const Duration(milliseconds: 10),
        maxDelay: const Duration(milliseconds: 40),
        delay: (duration) async => waits.add(duration),
      );

      expect(result.status, 'completed');
      expect(updates, ['running', 'running', 'completed']);
      expect(waits, const [
        Duration(milliseconds: 10),
        Duration(milliseconds: 20),
      ]);
    },
  );

  test('pricing polling is bounded', () async {
    final waits = <Duration>[];
    await expectLater(
      pollPricingRun(
        fetch: (_) async => _run('running'),
        runId: 'run-1',
        onUpdate: (_) {},
        maxAttempts: 3,
        delay: (duration) async => waits.add(duration),
      ),
      throwsA(
        isA<PricingRunPollingLimitExceeded>().having(
          (error) => error.attempts,
          'attempts',
          3,
        ),
      ),
    );
    expect(waits.length, 2);
  });

  testWidgets('pricing reason codes have RU/UK copy and neutral unknown copy', (
    tester,
  ) async {
    String? unknown;
    await tester.pumpWidget(
      MaterialApp(
        locale: const Locale('uk'),
        supportedLocales: const [Locale('ru'), Locale('uk')],
        localizationsDelegates: GlobalMaterialLocalizations.delegates,
        home: Builder(
          builder: (context) => Column(
            children: [
              Text(pricingReasonLabel(context, 'LOW_CONFIDENCE')),
              Text(
                pricingReasonLabel(
                  context,
                  'SOME_NEW_GATE_CODE',
                  onUnknown: (code) => unknown = code,
                ),
              ),
            ],
          ),
        ),
      ),
    );

    expect(find.text('низька впевненість'), findsOneWidget);
    expect(find.text('Невідома причина (SOME_NEW_GATE_CODE)'), findsOneWidget);
    expect(unknown, 'SOME_NEW_GATE_CODE');
  });

  testWidgets('admin can start a pricing run and sees completion', (
    tester,
  ) async {
    var startRequests = 0;
    var previewRequests = 0;
    var finishedCallbacks = 0;
    Map<String, dynamic>? startBody;
    final client = MockClient((request) async {
      if (request.method == 'GET' &&
          request.url.path == '/api/v1/pricing/runs') {
        return _jsonResponse({
          'items': <Object>[],
          'total': 0,
          'limit': 25,
          'offset': 0,
        });
      }
      if (request.method == 'GET' &&
          request.url.path == '/api/v1/catalog/imports') {
        return _jsonResponse({
          'items': [_importJson()],
          'total': 1,
          'limit': 100,
          'offset': 0,
        });
      }
      if (request.method == 'POST' &&
          request.url.path == '/api/v1/pricing/runs/preview') {
        previewRequests += 1;
        return _jsonResponse(_runScopePreviewJson());
      }
      if (request.method == 'POST' &&
          request.url.path == '/api/v1/pricing/runs') {
        startRequests += 1;
        startBody = jsonDecode(request.body) as Map<String, dynamic>;
        return _jsonResponse(_runJson('pending'), statusCode: 202);
      }
      if (request.method == 'GET' &&
          request.url.path == '/api/v1/pricing/runs/run-1') {
        return _jsonResponse(_runJson('completed'));
      }
      return http.Response('not found', 404);
    });
    await tester.pumpWidget(
      _app(
        client: client,
        child: PricingRunPanel(
          canAdministerWorkspace: true,
          onRunFinished: () => finishedCallbacks += 1,
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Расчёт ещё не запускался.'), findsOneWidget);
    await tester.tap(find.byKey(const ValueKey('pricing-run-start')));
    await tester.pumpAndSettle();
    expect(find.text('Запустить расчёт цен?'), findsOneWidget);
    await tester.tap(find.text('Запустить').last);
    await tester.pumpAndSettle();

    expect(startRequests, 1);
    expect(finishedCallbacks, 1);
    expect(find.text('Расчёт завершён'), findsOneWidget);
    expect(tester.takeException(), isNull);

    // Область замораживается до запуска, а не после него.
    expect(
      previewRequests,
      1,
      reason: 'запуск обязан сначала показать владельцу цену решения',
    );
    // Сервер отвергает полный каталог без явного согласия, поэтому клиент
    // обязан его передать — иначе владелец видит 422 вместо расчёта.
    expect(startBody?['confirm_full_catalog'], isTrue);
    expect(startBody?['scope_mode'], 'FULL_CATALOG');
    // Повторное нажатие на ту же область не должно создавать второй прогон.
    expect(startBody?['idempotency_key'], isNotNull);
    // Хеши клиент больше не шлёт: подтверждением служит непрозрачный токен,
    // выданный сервером вместе с предпросмотром.
    expect(startBody?['preview_token'], isNotNull);
    expect(startBody?.containsKey('expected_scope_hash'), isFalse);
    expect(startBody?.containsKey('expected_catalog_snapshot_hash'), isFalse);
  });

  testWidgets('member sees status but no pricing-run admin actions', (
    tester,
  ) async {
    var statusFetches = 0;
    final client = MockClient((request) async {
      if (request.url.path == '/api/v1/pricing/runs') {
        return _jsonResponse({
          'items': [_runJson('running')],
          'total': 1,
          'limit': 25,
          'offset': 0,
        });
      }
      if (request.url.path == '/api/v1/catalog/imports') {
        return _jsonResponse({
          'items': [_importJson()],
          'total': 1,
          'limit': 100,
          'offset': 0,
        });
      }
      if (request.url.path == '/api/v1/pricing/runs/run-1') {
        statusFetches += 1;
        return _jsonResponse(
          _runJson(statusFetches == 1 ? 'running' : 'completed'),
        );
      }
      return http.Response('not found', 404);
    });
    await tester.pumpWidget(
      _app(
        client: client,
        child: PricingRunPanel(
          canAdministerWorkspace: false,
          onRunFinished: () {},
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Расчёт выполняется'), findsOneWidget);
    expect(find.byKey(const ValueKey('pricing-run-start')), findsNothing);
    expect(find.byKey(const ValueKey('pricing-run-cancel')), findsNothing);
    expect(find.textContaining('доступны администратору'), findsOneWidget);
    expect(
      find.text('Номер расчёта для поддержки: corr-run-1'),
      findsOneWidget,
    );

    // Status is live for members too: the resumed poll carries the run to its
    // end without any admin control appearing.
    await tester.pump(const Duration(seconds: 2));
    await tester.pumpAndSettle();

    expect(statusFetches, 2);
    expect(find.text('Расчёт завершён'), findsOneWidget);
    expect(find.byKey(const ValueKey('pricing-run-cancel')), findsNothing);
  });

  testWidgets('discovery funnel loads lazily and exposes gate ceilings', (
    tester,
  ) async {
    var requests = 0;
    final client = MockClient((request) async {
      if (request.url.path == '/api/v1/operations/discovery-funnel') {
        requests += 1;
        expect(request.url.queryParameters['run_limit'], '400');
        return _jsonResponse(_discoveryFunnelJson());
      }
      return http.Response('not found', 404);
    });
    await tester.pumpWidget(
      _app(client: client, child: const DiscoveryFunnelPanel()),
    );
    await tester.pumpAndSettle();

    expect(requests, 0, reason: 'collapsed observability must not poll');
    await tester.tap(find.text('Почему конкуренты не попали в расчёт'));
    await tester.pumpAndSettle();

    expect(requests, 1);
    expect(
      find.textContaining('Получено от заявленного: 43.7%'),
      findsOneWidget,
    );
    expect(find.textContaining('OEM identity'), findsOneWidget);
    expect(find.textContaining('потолок разблокировки 34.8%'), findsOneWidget);
    expect(
      find.text('Номер расчёта для поддержки: corr-funnel-1'),
      findsOneWidget,
    );
  });

  testWidgets('export sends active filters and saves the returned bytes', (
    tester,
  ) async {
    Uri? requested;
    BinaryDownload? saved;
    final client = MockClient((request) async {
      requested = request.url;
      return http.Response.bytes(
        [0x50, 0x4b],
        200,
        headers: {
          'content-type':
              'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
          'content-disposition':
              'attachment; filename="marko-recommendations-run-1.xlsx"',
          'x-export-row-count': '17',
        },
      );
    });
    await tester.pumpWidget(
      _app(
        client: client,
        child: RecommendationExportButton(
          queue: 'raise',
          action: 'RAISE',
          sort: 'EXPECTED_GROSS_UPLIFT',
          saveDownload: (download) async {
            saved = download;
            return '/tmp/${download.filename}';
          },
        ),
      ),
    );

    await tester.tap(find.byKey(const ValueKey('recommendations-export')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Excel (.xlsx)'));
    await tester.pumpAndSettle();

    expect(requested?.path, '/api/v1/pricing/recommendations/export');
    expect(requested?.queryParameters, containsPair('queue', 'raise'));
    expect(requested?.queryParameters, containsPair('action', 'RAISE'));
    expect(
      requested?.queryParameters,
      containsPair('sort', 'EXPECTED_GROSS_UPLIFT'),
    );
    expect(requested?.queryParameters, containsPair('format', 'xlsx'));
    expect(saved?.filename, 'marko-recommendations-run-1.xlsx');
    expect(saved?.rowCount, 17);
    expect(saved?.bytes, [0x50, 0x4b]);
  });
}

Widget _app({required http.Client client, required Widget child}) {
  return ProviderScope(
    overrides: [
      apiClientProvider.overrideWithValue(
        ApiClient(client: client, baseUrl: 'https://api.example.test'),
      ),
    ],
    child: MaterialApp(
      theme: AppTheme.light,
      locale: const Locale('ru'),
      supportedLocales: const [Locale('ru'), Locale('uk')],
      localizationsDelegates: GlobalMaterialLocalizations.delegates,
      home: Scaffold(body: Center(child: child)),
    ),
  );
}

http.Response _jsonResponse(Object payload, {int statusCode = 200}) {
  return http.Response(
    jsonEncode(payload),
    statusCode,
    headers: {'content-type': 'application/json'},
  );
}

Map<String, dynamic> _previewJson() => {
  'filename': 'catalog.xlsx',
  'content_size': 3,
  'max_size_bytes': 26214400,
  'requires_sheet_choice': true,
  'sheets': [
    {
      'name': 'Export Products Sheet',
      'row_count': 4901,
      'headers': ['SKU', 'OE', 'Name', 'Category', 'Price'],
      'suggested_mapping': {
        'sku': 'SKU',
        'oe': 'OE',
        'name': 'Name',
        'category': 'Category',
        'price': 'Price',
      },
      'mapping_error': null,
      'sample_rows': [
        {
          'SKU': 'S-1',
          'OE': '7E5827505A',
          'Name': 'Замок',
          'Category': 'Замки',
          'Price': 1800,
        },
      ],
      'is_catalog_candidate': true,
    },
    {
      'name': 'Лист1',
      'row_count': 16,
      'headers': ['SKU', 'OE', 'Name', 'Category', 'Price'],
      'suggested_mapping': {
        'sku': 'SKU',
        'oe': 'OE',
        'name': 'Name',
        'category': 'Category',
        'price': 'Price',
      },
      'mapping_error': null,
      'sample_rows': <Object>[],
      'is_catalog_candidate': true,
    },
  ],
};

Map<String, dynamic> _importJson({String status = 'completed'}) => {
  'id': 'batch-1',
  'filename': 'catalog.xlsx',
  'status': status,
  'column_mapping': {
    'sku': 'SKU',
    'oe': 'OE',
    'name': 'Name',
    'category': 'Category',
    'price': 'Price',
  },
  'total_rows': 4901,
  'imported_rows': 4647,
  'rejected_rows': status == 'partial' ? 254 : 0,
  'error_log': status == 'partial'
      ? [
          {
            'row': 42,
            'code': 'NORMALIZED_OE_COLLISION',
            'message': 'NORMALIZED_OE_COLLISION: manual review required',
          },
        ]
      : <Object>[],
  'created_at': '2026-07-30T04:00:00Z',
};

PricingRunSummary _run(String status) =>
    PricingRunSummary.fromJson(_runJson(status));

Map<String, dynamic> _runJson(String status) => {
  'id': 'run-1',
  'import_batch_id': 'batch-1',
  'status': status,
  'coefficient_model': 'shrinkage',
  'coefficient_version': null,
  'calibration_dataset_hash': null,
  'calibration_accounting': {'correlation_id': 'corr-run-1'},
  'total_items': 10,
  'completed_items': status == 'completed' ? 10 : 2,
  'failed_items': 0,
  'manual_review_items': 1,
  'error': status == 'failed' ? 'worker died' : null,
  'created_at': '2026-07-30T04:00:00Z',
};

Map<String, dynamic> _discoveryFunnelJson() => {
  'generated_at': '2026-07-30T06:00:00Z',
  'correlation_id': 'corr-funnel-1',
  'sampled_runs': 400,
  'run_status_counts': {'completed': 399, 'failed': 1},
  'total_candidates': 4527,
  'status_counts': {
    'PRICING_EVIDENCE': 0,
    'REFERENCE_ONLY': 4010,
    'REJECTED': 517,
  },
  'selection_reasons': {'BRAND_RULES_NOT_APPROVED': 4010},
  'coverage': {
    'reported_total': 78332,
    'reported_known_runs': 399,
    'retrieved_count': 34239,
    'persisted_count': 4527,
    'rejected_count': 0,
    'owned_excluded_count': 127,
    'unfetched_count': 44093,
    'retrieval_coverage_ratio': '0.437101',
  },
  'gates': {
    'oem_identity': {
      'reached': 4527,
      'terminal': 1575,
      'survived': 2952,
      'conditional_pass_rate': '0.652087',
      'conditional_terminal_rate': '0.347913',
      'survival_ceiling_ratio': '0.652087',
      'single_gate_unlock_upper_bound': 1575,
      'single_gate_unlock_upper_bound_ratio': '0.347913',
      'counterfactual_ceiling_method': 'SHORT_CIRCUIT_UPPER_BOUND',
    },
  },
  'categories': [
    {
      'category': 'Тормозная система',
      'runs': 44,
      'total_candidates': 610,
      'status_counts': {'REFERENCE_ONLY': 610},
      'gates': <String, dynamic>{},
    },
  ],
};

/// Замороженная область ценового прогона.
///
/// Отдельное имя от `_previewJson`, который описывает предпросмотр импорта
/// каталога: формы разные, и подмена одной другой молча обнуляет подтверждение.
Map<String, dynamic> _runScopePreviewJson() => {
  'scope_contract_version': 'v1',
  'import_batch_id': 'batch-1',
  'scope_mode': 'FULL_CATALOG',
  'policy_version': 'test-v1',
  'catalog_snapshot_hash': 'a' * 64,
  'scope_hash': 'b' * 64,
  'preview_token': 'mrp1_testtoken0000000000000000000000000000',
  'requires_full_catalog_confirmation': true,
  'estimate': {
    'requested_items': 3,
    'eligible_items': 3,
    'excluded_items': 0,
    'unique_scrape_inputs': 3,
    'duplicate_items': 0,
    'worst_case_duration_seconds': 120,
  },
  'exclusions': <Map<String, dynamic>>[],
  'exclusions_truncated': false,
  'scope_manifest': <String, dynamic>{},
};
