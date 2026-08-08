import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/catalog/catalog_models.dart';
import 'package:marko_client/features/catalog/widgets/catalog_competitor_section.dart';

CatalogDiscoveredOffer _offer({
  required String id,
  required String title,
  required double price,
  required String status,
  required String reason,
  String? mpn,
  String? oeRaw,
}) {
  return CatalogDiscoveredOffer(
    discoveryOfferId: id,
    sourceListingId: id,
    sellerId: 'seller-$id',
    sellerName: 'Продавец $id',
    title: title,
    url: 'https://prom.ua/ua/p$id-item.html',
    sku: null,
    mpn: mpn,
    oeRaw: oeRaw,
    brand: 'Polcar',
    salePrice: price,
    referencePrice: null,
    currency: 'UAH',
    measureUnit: 'шт.',
    isAvailable: true,
    titleContainsQuery: true,
    identityStatus: 'QUERY_TOKEN_PRESENT',
    sourceConfidence: 1,
    reasonCodes: const [],
    selectionStatus: status,
    selectionReason: reason,
    passedGates: const [],
    selectionFlags: const [],
    selectionDetails: const {},
    predictedTier: 'unknown',
    tierConfidence: 0,
  );
}

final _evidence = _offer(
  id: '1',
  title: 'Замок 7E5827505A Polcar',
  price: 1900,
  status: 'PRICING_EVIDENCE',
  reason: 'OK',
);
final _reference = _offer(
  id: '2',
  title: 'Замок 7E5827505A без бренда',
  price: 1700,
  status: 'REFERENCE_ONLY',
  reason: 'TIER_UNKNOWN',
);
final _rejected = _offer(
  id: '3',
  title: 'Несопоставимое объявление 7E5827505A',
  price: 900,
  status: 'REJECTED',
  reason: 'OEM_NOT_FOUND',
);

CatalogCompetitorComparison _comparison({
  List<CatalogDiscoveredOffer> evidence = const [],
  List<CatalogDiscoveredOffer> reference = const [],
  List<CatalogDiscoveredOffer> discovery = const [],
  List<CatalogCompetitorOffer> candidates = const [],
  double? recommended,
  List<String> reasons = const [],
}) {
  return CatalogCompetitorComparison(
    recommendationId: 'rec-1',
    comparedAt: DateTime.utc(2026, 7, 28, 10),
    currentPrice: 1800,
    fairPrice: 1830,
    recommendedPrice: recommended,
    currency: 'UAH',
    reasonCodes: reasons,
    items: const [],
    discoveryRunId: 'run-1',
    discoveryQuery: '7E5827505A',
    discoveredTotal: discovery.isEmpty
        ? evidence.length + reference.length
        : discovery.length,
    pricingEvidenceCount: evidence.length,
    referenceOnlyCount: reference.length,
    rejectedCandidateCount: 4,
    confidenceGrade: 'MEDIUM',
    dispersion: 0.1516,
    discoveryItems: discovery,
    pricingEvidence: evidence,
    referenceOnly: reference,
    candidateItems: candidates,
  );
}

final _automaticCandidate = CatalogCompetitorOffer(
  observationId: 'candidate-observation',
  sellerId: 'candidate-seller',
  sellerName: 'Другой продавец',
  title: 'Фен VGR V-493 Зелёный',
  url: 'https://prom.ua/ua/p4-item.html',
  price: 799,
  currency: 'UAH',
  isAvailable: true,
  normalizedPrice: null,
  tier: 'unknown',
  matchConfidence: 0.81,
  observedAt: DateTime.utc(2026, 8, 8, 9),
  reasonCodes: const [
    'MANUAL_MISSING_OE_PROVENANCE',
    'MANUAL_MISSING_CONDITION',
  ],
);

Widget _app(
  CatalogCompetitorComparison comparison, {
  List<String> opened = const [],
}) {
  return MaterialApp(
    theme: AppTheme.light,
    locale: const Locale('ru'),
    supportedLocales: const [Locale('ru'), Locale('uk')],
    localizationsDelegates: GlobalMaterialLocalizations.delegates,
    home: Scaffold(
      body: SingleChildScrollView(
        child: CatalogCompetitorSection(
          comparison: comparison,
          onOpenListing: (url) => opened.add(url),
        ),
      ),
    ),
  );
}

void main() {
  testWidgets('automatic run candidates stay visible before verification', (
    tester,
  ) async {
    await tester.pumpWidget(
      _app(_comparison(candidates: [_automaticCandidate])),
    );
    await tester.pumpAndSettle();

    expect(find.text('Найдено, но ещё не подтверждено'), findsOneWidget);
    expect(
      find.text(
        'Подтверждённых конкурентов пока нет. Найденные объявления показаны '
        'ниже — для них нужна проверка модели и состояния.',
      ),
      findsOneWidget,
    );
    expect(
      find.text(
        'В последнем расчёте не осталось подходящих конкурентных объявлений.',
      ),
      findsNothing,
    );
    expect(find.text('Фен VGR V-493 Зелёный'), findsOneWidget);
    expect(find.text('Нужна проверка модели и состояния'), findsOneWidget);
  });

  testWidgets('both outcome blocks are rendered and labelled', (tester) async {
    await tester.pumpWidget(
      _app(_comparison(evidence: [_evidence], reference: [_reference])),
    );
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey('catalog-pricing-evidence-block')),
      findsOneWidget,
    );
    expect(
      find.text('Предварительно прошли ворота · пока не в расчёте · 1'),
      findsOneWidget,
    );
    expect(
      find.text('Показаны справочно · в расчёт не входят · 1'),
      findsOneWidget,
    );
    expect(find.text('Замок 7E5827505A Polcar'), findsOneWidget);
    expect(find.text('Замок 7E5827505A без бренда'), findsOneWidget);
  });

  testWidgets('every listing in both blocks is openable', (tester) async {
    final opened = <String>[];
    await tester.pumpWidget(
      _app(
        _comparison(evidence: [_evidence], reference: [_reference]),
        opened: opened,
      ),
    );
    await tester.pumpAndSettle();

    for (final title in const [
      'Замок 7E5827505A Polcar',
      'Замок 7E5827505A без бренда',
    ]) {
      await tester.ensureVisible(find.text(title));
      await tester.pumpAndSettle();
      await tester.tap(find.text(title));
      await tester.pumpAndSettle();
    }

    expect(opened, [
      'https://prom.ua/ua/p1-item.html',
      'https://prom.ua/ua/p2-item.html',
    ]);
  });

  testWidgets('parsed native MPN/OE evidence is visible on the card', (
    tester,
  ) async {
    final offer = _offer(
      id: 'native-identity',
      title: 'Амортизатор Mercedes',
      price: 950,
      status: 'REFERENCE_ONLY',
      reason: 'SEMANTIC_UNCONFIRMED',
      mpn: 'MA-00290',
      oeRaw: '170450',
    );
    await tester.pumpWidget(
      _app(_comparison(discovery: [offer], reference: [offer])),
    );
    await tester.pumpAndSettle();

    expect(find.textContaining('MPN MA-00290'), findsOneWidget);
    expect(find.textContaining('OE 170450'), findsOneWidget);
  });

  testWidgets('parsed candidates remain visible even when rejected', (
    tester,
  ) async {
    await tester.pumpWidget(
      _app(
        _comparison(
          evidence: [_evidence],
          reference: [_reference],
          discovery: [_evidence, _reference, _rejected],
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey('catalog-parser-candidates-block')),
      findsOneWidget,
    );
    expect(
      find.text('Остальные объявления из выдачи парсера · 1'),
      findsOneWidget,
    );
    expect(find.text('Несопоставимое объявление 7E5827505A'), findsOneWidget);
    expect(find.textContaining('Отброшен'), findsOneWidget);
    expect(find.text('Замок 7E5827505A Polcar'), findsOneWidget);
    expect(find.text('Замок 7E5827505A без бренда'), findsOneWidget);
  });

  testWidgets('an empty pricing basis says so instead of showing nothing', (
    tester,
  ) async {
    await tester.pumpWidget(_app(_comparison(reference: [_reference])));
    await tester.pumpAndSettle();

    expect(
      find.textContaining('Discovery-кандидаты не допускаются к расчёту цены'),
      findsOneWidget,
    );
    expect(
      find.text('Показаны справочно · в расчёт не входят · 1'),
      findsOneWidget,
    );
  });

  testWidgets('calculation card explains silence instead of leaving a blank', (
    tester,
  ) async {
    await tester.pumpWidget(
      _app(
        _comparison(
          evidence: [_evidence],
          reasons: const ['CHANGE_BELOW_SIGNIFICANCE_THRESHOLD'],
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey('catalog-price-calculation')),
      findsOneWidget,
    );
    expect(
      find.text('Рекомендация не выдаётся: изменение ниже порога значимости.'),
      findsOneWidget,
    );
    expect(find.text('15.2% · MEDIUM'), findsOneWidget);
  });

  testWidgets('calculation card shows the recommendation and its delta', (
    tester,
  ) async {
    await tester.pumpWidget(
      _app(_comparison(evidence: [_evidence], recommended: 1980)),
    );
    await tester.pumpAndSettle();

    expect(find.text('Рекомендация: 1980 UAH (+10.0%)'), findsOneWidget);
  });
}
