import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/app_language.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/pricing/pricing_controller.dart';
import 'package:marko_client/features/pricing/pricing_models.dart';
import 'package:marko_client/features/pricing/recommendations_page.dart';

/// An empty queue tab must not be reported as an empty system.
///
/// The screen used to answer "0 позиций, подключите магазины" while a finished
/// run held eight recommendations under the review tab, because both the tiles
/// and the empty state were derived from the filtered page instead of the run.
void main() {
  testWidgets('an empty tab points at the tab that holds the work', (
    tester,
  ) async {
    await tester.pumpWidget(
      _app(
        const RecommendationsState(
          page: RecommendationPage(
            items: [],
            total: 0,
            runId: 'run-1',
            actionCounts: RecommendationActionCounts(
              raise: 0,
              lower: 0,
              review: 8,
              hold: 0,
              total: 8,
            ),
          ),
          queue: 'raise',
          sort: 'ABSOLUTE_RECOMMENDED_CHANGE',
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('В этой вкладке пусто'), findsOneWidget);
    expect(
      find.textContaining('В расчёте есть позиции (8)'),
      findsOneWidget,
      reason: 'the operator must learn the run is not empty',
    );
    expect(find.text('Показать все (8)'), findsOneWidget);
    expect(find.text('Проверить вручную (8)'), findsOneWidget);
    expect(
      find.textContaining('Подключите магазины'),
      findsNothing,
      reason: 'nothing is wrong with the stores; the filter is the cause',
    );

    // The tiles describe the run, so "8" stays visible while standing on an
    // empty tab.
    expect(find.text('Позиций в расчёте'), findsOneWidget);
    expect(find.text('8'), findsWidgets);
  });

  testWidgets('a genuinely empty run asks for a calculation, not for stores', (
    tester,
  ) async {
    await tester.pumpWidget(
      _app(
        const RecommendationsState(
          page: RecommendationPage(
            items: [],
            total: 0,
            runId: null,
            actionCounts: RecommendationActionCounts(),
          ),
          queue: 'all',
          sort: 'ABSOLUTE_RECOMMENDED_CHANGE',
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Пока нет рекомендаций'), findsOneWidget);
    expect(find.textContaining('Запустите расчёт'), findsOneWidget);
    expect(find.textContaining('Показать все'), findsNothing);
  });
}

Widget _app(RecommendationsState state) {
  return ProviderScope(
    retry: (_, _) => null,
    overrides: [
      recommendationsControllerProvider.overrideWith(
        () => _StaticRecommendationsController(state),
      ),
    ],
    child: Consumer(
      builder: (context, ref, _) {
        final language = ref.watch(appLanguageProvider);
        return MaterialApp(
          theme: AppTheme.light,
          locale: language.locale,
          supportedLocales: const [Locale('ru'), Locale('uk')],
          localizationsDelegates: GlobalMaterialLocalizations.delegates,
          home: const Scaffold(body: RecommendationsPage()),
        );
      },
    ),
  );
}

class _StaticRecommendationsController extends RecommendationsController {
  _StaticRecommendationsController(this._state);

  final RecommendationsState _state;

  @override
  Future<RecommendationsState> build() async => _state;
}
