import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/auth/auth_controller.dart';
import 'package:marko_client/features/auth/auth_models.dart';
import 'package:marko_client/features/dashboard/dashboard_page.dart';
import 'package:marko_client/features/pricing/pricing_controller.dart';
import 'package:marko_client/features/pricing/pricing_models.dart';
import 'package:marko_client/features/stores/store_models.dart';
import 'package:marko_client/features/stores/stores_controller.dart';

void main() {
  testWidgets('Мои магазины is a separate desktop destination', (tester) async {
    tester.view.physicalSize = const Size(1200, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(_testApp());

    expect(find.text('Магазины'), findsOneWidget);
    expect(find.text('Мои магазины'), findsOneWidget);

    await tester.tap(find.text('Магазины'));
    await tester.pumpAndSettle();
    expect(find.byTooltip('Удалить магазин'), findsNothing);

    await tester.tap(find.text('Мои магазины'));
    await tester.pumpAndSettle();

    expect(find.text('Мои магазины'), findsNWidgets(3));
    expect(find.text('Подключённые'), findsOneWidget);
    expect(find.text('Kemp'), findsOneWidget);
    expect(find.text('Market competitor'), findsNothing);
    expect(find.byTooltip('Удалить магазин'), findsOneWidget);

    await tester.tap(find.byTooltip('Удалить магазин'));
    await tester.pumpAndSettle();
    expect(find.text('Удалить магазин?'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('confirm-delete-store')));
    await tester.pumpAndSettle();
    expect(find.text('Kemp'), findsNothing);
    expect(find.text('Магазинов пока нет'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('five destinations fit in the mobile navigation', (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(_testApp());

    expect(find.text('Мои магазины'), findsOneWidget);
    expect(find.text('Обзор'), findsOneWidget);

    await tester.tap(find.text('Мои магазины'));
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);
  });
}

Widget _testApp() {
  return ProviderScope(
    overrides: [
      authControllerProvider.overrideWith(_TestAuthController.new),
      recommendationsControllerProvider.overrideWith(
        _TestRecommendationsController.new,
      ),
      storesControllerProvider.overrideWith(_TestStoresController.new),
    ],
    child: MaterialApp(theme: AppTheme.light, home: const DashboardPage()),
  );
}

class _TestAuthController extends AuthController {
  @override
  Future<MarkoAuthState> build() async => MarkoAuthState.initial;
}

class _TestRecommendationsController extends RecommendationsController {
  @override
  Future<RecommendationsState> build() async {
    return const RecommendationsState(
      page: RecommendationPage(items: [], total: 0, runId: null),
      queue: 'all',
      sort: 'ABSOLUTE_RECOMMENDED_CHANGE',
    );
  }
}

class _TestStoresController extends StoresController {
  @override
  Future<StoresState> build() async {
    return const StoresState(
      stores: [
        StoreSummary(
          id: 'owned-store',
          externalId: '1',
          name: 'Kemp',
          url: 'https://kemp.prom.ua',
          kind: 'owned',
          productCount: 12,
          lastSyncedAt: null,
        ),
        StoreSummary(
          id: 'competitor-store',
          externalId: '2',
          name: 'Market competitor',
          url: 'https://competitor.prom.ua',
          kind: 'competitor',
          productCount: 8,
          lastSyncedAt: null,
        ),
      ],
    );
  }

  @override
  Future<bool> deleteStore(StoreSummary store) async {
    final current = state.requireValue;
    state = AsyncData(
      current.copyWith(
        stores: current.stores
            .where((item) => item.id != store.id)
            .toList(growable: false),
      ),
    );
    return true;
  }
}
