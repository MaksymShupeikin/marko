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
}) {
  return CatalogDiscoveredOffer(
    discoveryOfferId: id,
    sourceListingId: id,
    sellerId: 'seller-$id',
    sellerName: 'Продавец $id',
    title: title,
    url: 'https://prom.ua/ua/p$id-item.html',
    sku: null,
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

CatalogCompetitorComparison _comparison({
  List<CatalogDiscoveredOffer> evidence = const [],
  List<CatalogDiscoveredOffer> reference = const [],
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
    discoveredTotal: evidence.length + reference.length,
    pricingEvidenceCount: evidence.length,
    referenceOnlyCount: reference.length,
    rejectedCandidateCount: 4,
    confidenceGrade: 'MEDIUM',
    dispersion: 0.1516,
    pricingEvidence: evidence,
    referenceOnly: reference,
  );
}

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
  testWidgets('both outcome blocks are rendered and labelled', (tester) async {
    await tester.pumpWidget(
      _app(_comparison(evidence: [_evidence], reference: [_reference])),
    );
    await tester.pumpAndSettle();

    expect(
      find.byKey(const ValueKey('catalog-pricing-evidence-block')),
      findsOneWidget,
    );
    expect(find.text('Учитываются в расчёте · 1'), findsOneWidget);
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

  testWidgets('an empty pricing basis says so instead of showing nothing', (
    tester,
  ) async {
    await tester.pumpWidget(_app(_comparison(reference: [_reference])));
    await tester.pumpAndSettle();

    expect(
      find.textContaining('ни одно объявление не допущено к расчёту цены'),
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
