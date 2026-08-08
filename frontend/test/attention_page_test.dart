import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/app_language.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/attention/attention_controller.dart';
import 'package:marko_client/features/attention/attention_models.dart';
import 'package:marko_client/features/attention/attention_page.dart';

void main() {
  testWidgets('shows price direction and evidence in the daily queue', (
    tester,
  ) async {
    var openedRecommendation = '';
    final product = AttentionProduct(
      productId: 'product-1',
      recommendationId: 'recommendation-1',
      name: 'Амортизатор передний',
      sku: 'SKU-42',
      oe: '8E0413031',
      brand: 'Sachs',
      sourceKind: 'XLSX',
      sourceId: 'source-1',
      status: 'OVERPRICED',
      severity: 18,
      ourPrice: '1200',
      marketLow: '950',
      marketHigh: '1050',
      suggestedPrice: '1000',
      currency: 'UAH',
      differencePercent: '20',
      confidence: '0.84',
      evidenceCount: 5,
      reasonCodes: const ['MARKET_PRICE_LOWER'],
      marketCheckedAt: DateTime.utc(2026, 8, 7, 10),
      updatedAt: DateTime.utc(2026, 8, 7, 10),
    );
    final state = AttentionState(
      summary: AttentionSummary(
        total: 1,
        overpriced: 1,
        underpriced: 0,
        inMarket: 0,
        reviewRequired: 0,
        noData: 0,
        processing: 0,
        updatedAt: DateTime.utc(2026, 8, 7, 10),
      ),
      page: AttentionPageResult(
        items: [product],
        total: 1,
        limit: 50,
        offset: 0,
      ),
    );

    await tester.pumpWidget(
      _app(
        state,
        onOpenRecommendation: (value) => openedRecommendation = value,
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('1 позиция требует внимания'), findsOneWidget);
    expect(find.text('Амортизатор передний'), findsOneWidget);
    expect(find.textContaining('1200 UAH'), findsOneWidget);
    expect(find.textContaining('950–1050 UAH'), findsOneWidget);
    expect(find.textContaining('5 подтверждённых продавцов'), findsOneWidget);

    await tester.tap(find.byTooltip('Открыть доказательства'));
    expect(openedRecommendation, 'recommendation-1');
  });

  testWidgets('empty queue sends the user to product sources', (tester) async {
    var sourcesOpened = false;
    const state = AttentionState(
      summary: AttentionSummary(
        total: 0,
        overpriced: 0,
        underpriced: 0,
        inMarket: 0,
        reviewRequired: 0,
        noData: 0,
        processing: 0,
        updatedAt: null,
      ),
      page: AttentionPageResult(items: [], total: 0, limit: 50, offset: 0),
    );

    await tester.pumpWidget(
      _app(state, onOpenSources: () => sourcesOpened = true),
    );
    await tester.pumpAndSettle();

    expect(find.text('Цены под контролем'), findsOneWidget);
    expect(find.text('Подключить источник'), findsOneWidget);
    await tester.tap(find.text('Подключить источник'));
    expect(sourcesOpened, isTrue);
  });
}

Widget _app(
  AttentionState state, {
  VoidCallback? onOpenSources,
  ValueChanged<String>? onOpenRecommendation,
}) {
  return ProviderScope(
    retry: (_, _) => null,
    overrides: [
      attentionControllerProvider.overrideWith(
        () => _StaticAttentionController(state),
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
          home: Scaffold(
            body: AttentionPage(
              onOpenSources: onOpenSources ?? () {},
              onOpenRecommendation: onOpenRecommendation,
            ),
          ),
        );
      },
    ),
  );
}

class _StaticAttentionController extends AttentionController {
  _StaticAttentionController(this._state);

  final AttentionState _state;

  @override
  Future<AttentionState> build() async => _state;
}
