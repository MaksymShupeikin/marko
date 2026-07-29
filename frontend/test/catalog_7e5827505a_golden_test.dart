@Tags(['golden'])
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:marko_client/core/app_theme.dart';
import 'package:marko_client/features/catalog/catalog_models.dart';
import 'package:marko_client/features/catalog/widgets/catalog_competitor_section.dart';

/// Renders the card for 7E5827505A on the recorded run and writes a PNG.
///
/// The distribution is the one the live run produced: nothing in the pricing
/// basis, twenty-five reference-only listings, four rejected.
CatalogDiscoveredOffer _offer(int index, String seller, double price) {
  return CatalogDiscoveredOffer(
    discoveryOfferId: 'offer-$index',
    sourceListingId: '$index',
    sellerId: 'seller-$index',
    sellerName: seller,
    title: 'Замок кришки багажника 7E5827505A VW Transporter T5 T6',
    url: 'https://prom.ua/ua/p$index-zamok.html',
    sku: '7E5827505A',
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
    selectionStatus: 'REFERENCE_ONLY',
    selectionReason: 'TIER_UNKNOWN',
    passedGates: const [],
    selectionFlags: const [],
    selectionDetails: const {},
    predictedTier: 'unknown',
    tierConfidence: 0,
  );
}

Future<void> _loadRealFonts() async {
  // The test binding ships only the placeholder font, which would render every
  // label as a box.  A real face makes the screenshot legible.
  for (final entry in const {
    'Roboto': '/System/Library/Fonts/Supplemental/Arial.ttf',
    'RobotoBold': '/System/Library/Fonts/Supplemental/Arial Bold.ttf',
  }.entries) {
    final file = File(entry.value);
    if (!file.existsSync()) continue;
    final loader = FontLoader(entry.key)
      ..addFont(Future.value(file.readAsBytesSync().buffer.asByteData()));
    await loader.load();
  }
}

void main() {
  setUpAll(_loadRealFonts);

  testWidgets('7E5827505A card', (tester) async {
    tester.view.physicalSize = const Size(880, 1900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    const sellers = [
      'АвтоМаркет',
      'Zapchasti UA',
      'Autoparts IF',
      'Detali Plus',
      'AutoLux',
    ];
    final reference = List.generate(
      25,
      (index) =>
          _offer(index + 1, sellers[index % sellers.length], 1600 + index * 20),
    );
    final comparison = CatalogCompetitorComparison(
      recommendationId: 'rec-1',
      comparedAt: DateTime.utc(2026, 7, 28, 12, 30),
      currentPrice: 1800,
      fairPrice: 1830,
      recommendedPrice: null,
      currency: 'UAH',
      reasonCodes: const ['CHANGE_BELOW_SIGNIFICANCE_THRESHOLD'],
      items: const [],
      discoveryRunId: 'aa621d41-646b-4875-bb0c-138423901a8a',
      discoveredAt: DateTime.utc(2026, 7, 28, 12, 30),
      discoveryQuery: '7E5827505A',
      discoveryStatus: 'completed',
      promReportedTotal: 90,
      discoveredTotal: 29,
      discoveryRetrievedCount: 29,
      discoveryPersistedCount: 29,
      pricingEvidenceCount: 0,
      referenceOnlyCount: 25,
      rejectedCandidateCount: 4,
      selectionHistogram: const {
        'REFERENCE_ONLY:TIER_UNKNOWN': 25,
        'REJECTED:DISMANTLER_SELLER': 2,
        'REJECTED:OEM_NOT_FOUND': 1,
        'REJECTED:USED': 1,
      },
      searchPagesFetched: 1,
      searchPageLimit: 1,
      unfetchedCount: 61,
      coverageRatio: 29 / 90,
      coverageReason: 'SEARCH_PAGE_LIMIT',
      selectionMethodVersion: 'deterministic-candidate-gates-v1',
      selectionConfigSha256: '9315cf08',
      brandRulesDatasetId: 'metis-prom-ua-live-30-oe-2026-07-19',
      confidenceGrade: 'MEDIUM',
      dispersion: 0.1516,
      discoveryItems: reference,
      pricingEvidence: const [],
      referenceOnly: reference,
    );

    await tester.pumpWidget(
      MaterialApp(
        theme: AppTheme.light.copyWith(
          textTheme: AppTheme.light.textTheme.apply(fontFamily: 'Roboto'),
        ),
        locale: const Locale('ru'),
        supportedLocales: const [Locale('ru'), Locale('uk')],
        localizationsDelegates: GlobalMaterialLocalizations.delegates,
        home: Scaffold(
          body: SingleChildScrollView(
            padding: const EdgeInsets.all(20),
            child: CatalogCompetitorSection(
              comparison: comparison,
              onOpenListing: (_) {},
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await expectLater(
      find.byType(CatalogCompetitorSection),
      matchesGoldenFile('goldens/catalog_7e5827505a.png'),
    );
  });
}
