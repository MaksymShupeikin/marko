import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/stores/store_models.dart';
import 'package:marko_client/features/stores/stores_controller.dart';
import 'package:marko_client/features/stores/stores_page.dart';

void main() {
  testWidgets('owned stores use original Prom names without a page dropdown', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1000, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          storesControllerProvider.overrideWith(_TestStoresController.new),
        ],
        child: MaterialApp(
          theme: AppTheme.light,
          home: const Scaffold(
            body: StoresPage(ownedOnly: true, canAdministerWorkspace: true),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byKey(const ValueKey('owned-store-dropdown')), findsNothing);
    expect(find.text('KEMP'), findsOneWidget);
    expect(find.text('ПРОФПАРТС'), findsOneWidget);
    expect(find.text('kemp'), findsNothing);
    expect(find.text('profparts'), findsNothing);

    expect(tester.takeException(), isNull);
  });

  testWidgets('member sees stores but not administrative controls', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1000, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          storesControllerProvider.overrideWith(_TestStoresController.new),
        ],
        child: MaterialApp(
          theme: AppTheme.light,
          home: const Scaffold(body: StoresPage(ownedOnly: true)),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('KEMP'), findsOneWidget);
    expect(
      find.textContaining(
        'Подключение, синхронизация и удаление магазинов доступны',
      ),
      findsOneWidget,
    );
    expect(find.text('Подключить магазин'), findsNothing);
    expect(find.byTooltip('Удалить магазин'), findsNothing);
  });

  testWidgets('active sync exposes bounded operator telemetry', (tester) async {
    tester.view.physicalSize = const Size(1000, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          storesControllerProvider.overrideWith(_TelemetryStoresController.new),
        ],
        child: MaterialApp(
          theme: AppTheme.light,
          home: const Scaffold(
            body: StoresPage(ownedOnly: true, canAdministerWorkspace: true),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Страницы: 12'), findsOneWidget);
    expect(find.text('Извлечено: 240'), findsOneWidget);
    expect(find.text('Сохранено: 230'), findsOneWidget);
    expect(find.text('Дубликаты: 10'), findsOneWidget);
    expect(find.text('Запуски задачи: 2/4'), findsOneWidget);
    expect(find.text('Повторные доставки: 1'), findsOneWidget);
    expect(find.text('Полнота структуры: 87.5%'), findsOneWidget);
    expect(find.text('Покрытие доказательств: 91.0%'), findsOneWidget);
    expect(find.textContaining('Дедлайн:'), findsOneWidget);
    expect(find.textContaining('Lease до:'), findsOneWidget);
    expect(find.textContaining('internal-task-id'), findsNothing);
    expect(tester.takeException(), isNull);
  });
}

class _TestStoresController extends StoresController {
  @override
  Future<StoresState> build() async {
    return const StoresState(
      stores: [
        StoreSummary(
          id: 'kemp-store',
          externalId: '2847093',
          name: 'KEMP',
          url: 'https://prom.ua/ua/c2847093-kemp.html',
          kind: 'owned',
          productCount: 10000,
          lastSyncedAt: null,
        ),
        StoreSummary(
          id: 'profparts-store',
          externalId: '3325174',
          name: 'ПРОФПАРТС',
          url: 'https://prom.ua/ua/c3325174-profparts.html',
          kind: 'owned',
          productCount: 725,
          lastSyncedAt: null,
        ),
      ],
    );
  }
}

class _TelemetryStoresController extends StoresController {
  @override
  Future<StoresState> build() async {
    return StoresState(
      activeSync: const StoreSync(
        storeId: 'kemp-store',
        syncRunId: 'run-1',
        status: 'running',
      ),
      activeJob: SyncRun(
        status: 'running',
        progressCurrent: 230,
        progressTotal: 300,
        error: null,
        taskExecutions: 2,
        taskRedeliveries: 1,
        maxTaskExecutions: 4,
        deadlineAt: DateTime.parse('2026-07-30T12:00:00Z'),
        ownerTaskId: 'internal-task-id',
        leaseExpiresAt: DateTime.parse('2026-07-30T11:45:00Z'),
        catalogPages: 12,
        productsExtracted: 240,
        productsPersisted: 230,
        duplicateProducts: 10,
        structuredCompleteness: 0.875,
        evidenceCoverage: 0.91,
      ),
    );
  }
}
