import '../../core/presentation_formatters.dart';

class CatalogStorePresence {
  CatalogStorePresence({
    required this.storeId,
    required this.externalId,
    required this.name,
    required this.url,
    required this.listingUrl,
    required this.listingCount,
    required Object? price,
    required this.currency,
    required this.isAvailable,
    this.isOwned = true,
    this.listingId,
    this.sourceListingId,
    this.snapshotAt,
  }) : price = DecimalValue.tryParse(price);

  factory CatalogStorePresence.fromJson(Map<String, dynamic> json) {
    return CatalogStorePresence(
      storeId: json['store_id'] as String,
      externalId: json['external_id'] as String,
      name: json['name'] as String,
      url: json['url'] as String,
      listingUrl: json['listing_url'] as String,
      listingCount: (json['listing_count'] as num).toInt(),
      price: json['price'],
      currency: json['currency'] as String,
      isAvailable: json['is_available'] as bool?,
      isOwned: json['is_owned'] as bool? ?? true,
      listingId: json['listing_id'] as String?,
      sourceListingId: json['source_listing_id'] as String?,
      snapshotAt: json['snapshot_at'] == null
          ? null
          : DateTime.parse(json['snapshot_at'] as String),
    );
  }

  final String storeId;
  final String externalId;
  final String name;
  final String url;
  final String listingUrl;
  final int listingCount;
  final DecimalValue? price;
  final String currency;
  final bool? isAvailable;
  final bool isOwned;
  final String? listingId;
  final String? sourceListingId;
  final DateTime? snapshotAt;

  String get tooltip {
    final parts = <String>[
      name,
      if (price != null) '${price!.toStringAsFixed(2)} $currency',
      if (listingCount > 1) '$listingCount объявления объединены',
    ];
    return parts.join(' · ');
  }
}

class CatalogStoreOption {
  const CatalogStoreOption({
    required this.storeId,
    required this.externalId,
    required this.name,
  });

  factory CatalogStoreOption.fromJson(Map<String, dynamic> json) {
    return CatalogStoreOption(
      storeId: json['store_id'] as String,
      externalId: json['external_id'] as String,
      name: json['name'] as String,
    );
  }

  final String storeId;
  final String externalId;
  final String name;
}

class CatalogProduct {
  CatalogProduct({
    required this.id,
    required this.identityKind,
    required this.name,
    required this.sku,
    required this.oe,
    this.mpn,
    required this.modelId,
    required this.brand,
    required this.imageUrl,
    required Object? priceMin,
    required Object? priceMax,
    required this.currency,
    required this.listingCount,
    required this.stores,
    Object? recommendedPrice,
    this.recommendationCurrency,
    this.recommendationAction,
    this.recommendationComputedAt,
    this.internalCode,
    this.kempLinkStatus,
    this.identityStatus,
    this.catalogDataEvidence,
    this.ownedListings = const [],
  }) : priceMin = DecimalValue.tryParse(priceMin),
       priceMax = DecimalValue.tryParse(priceMax),
       recommendedPrice = DecimalValue.tryParse(recommendedPrice);

  factory CatalogProduct.fromJson(Map<String, dynamic> json) {
    return CatalogProduct(
      id: json['id'] as String,
      identityKind: json['identity_kind'] as String,
      name: json['name'] as String,
      sku: json['sku'] as String?,
      oe: json['oe'] as String?,
      mpn: json['mpn'] as String?,
      modelId: json['model_id'] as String?,
      brand: json['brand'] as String?,
      imageUrl: json['image_url'] as String?,
      priceMin: json['price_min'],
      priceMax: json['price_max'],
      currency: json['currency'] as String?,
      listingCount: (json['listing_count'] as num).toInt(),
      stores: (json['stores'] as List<dynamic>)
          .map(
            (item) =>
                CatalogStorePresence.fromJson(item as Map<String, dynamic>),
          )
          .toList(growable: false),
      recommendedPrice: json['recommended_price'],
      recommendationCurrency: json['recommendation_currency'] as String?,
      recommendationAction: json['recommendation_action'] as String?,
      recommendationComputedAt: json['recommendation_computed_at'] == null
          ? null
          : DateTime.parse(json['recommendation_computed_at'] as String),
      internalCode: json['internal_code'] as String?,
      kempLinkStatus: json['kemp_link_status'] as String?,
      identityStatus: json['identity_status'] as String?,
      catalogDataEvidence: (json['catalog_data_evidence'] as Map?)
          ?.cast<String, dynamic>(),
      ownedListings: (json['owned_listings'] as List<dynamic>? ?? const [])
          .map(
            (item) =>
                CatalogStorePresence.fromJson(item as Map<String, dynamic>),
          )
          .toList(growable: false),
    );
  }

  final String id;
  final String identityKind;
  final String name;
  final String? sku;
  final String? oe;
  final String? mpn;
  final String? modelId;
  final String? brand;
  final String? imageUrl;
  final DecimalValue? priceMin;
  final DecimalValue? priceMax;
  final String? currency;
  final int listingCount;
  final List<CatalogStorePresence> stores;
  final DecimalValue? recommendedPrice;
  final String? recommendationCurrency;
  final String? recommendationAction;
  final DateTime? recommendationComputedAt;
  final String? internalCode;
  final String? kempLinkStatus;
  final String? identityStatus;
  final Map<String, dynamic>? catalogDataEvidence;
  final List<CatalogStorePresence> ownedListings;

  bool get isDuplicate => listingCount > 1;
  bool get isInMultipleStores => stores.length > 1;
  bool get hasRaiseRecommendation =>
      recommendationAction == 'RAISE' && recommendedPrice != null;
  bool get hasLowerRecommendation =>
      recommendationAction == 'LOWER' && recommendedPrice != null;

  CatalogStorePresence? get primaryStore {
    for (final store in stores) {
      if (store.isOwned) return store;
    }
    return null;
  }

  String get primaryPriceLabel {
    final store = primaryStore;
    if (store?.price == null) return priceLabel;
    return '${store!.price!.toStringAsFixed(2)} ${store.currency}';
  }

  String get priceLabel {
    final minimum = priceMin;
    final maximum = priceMax;
    final unit = currency;
    if (minimum == null || maximum == null || unit == null) {
      return 'Цена не указана';
    }
    if ((maximum - minimum).abs() < 0.005) {
      return '${minimum.toStringAsFixed(2)} $unit';
    }
    return '${minimum.toStringAsFixed(2)}–${maximum.toStringAsFixed(2)} $unit';
  }
}

class CatalogProductPage {
  const CatalogProductPage({
    required this.items,
    required this.total,
    required this.catalogTotal,
    required this.listingTotal,
    required this.duplicatesRemoved,
    required this.storeTotal,
    required this.stores,
    this.limit = 48,
    this.offset = 0,
  });

  factory CatalogProductPage.fromJson(Map<String, dynamic> json) {
    return CatalogProductPage(
      items: (json['items'] as List<dynamic>)
          .map((item) => CatalogProduct.fromJson(item as Map<String, dynamic>))
          .toList(growable: false),
      total: (json['total'] as num).toInt(),
      catalogTotal: (json['catalog_total'] as num).toInt(),
      listingTotal: (json['listing_total'] as num).toInt(),
      duplicatesRemoved: (json['duplicates_removed'] as num).toInt(),
      storeTotal: (json['store_total'] as num).toInt(),
      stores: (json['stores'] as List<dynamic>)
          .map(
            (item) => CatalogStoreOption.fromJson(item as Map<String, dynamic>),
          )
          .toList(growable: false),
      limit: (json['limit'] as num?)?.toInt() ?? 48,
      offset: (json['offset'] as num?)?.toInt() ?? 0,
    );
  }

  final List<CatalogProduct> items;
  final int total;
  final int catalogTotal;
  final int listingTotal;
  final int duplicatesRemoved;
  final int storeTotal;
  final List<CatalogStoreOption> stores;
  final int limit;
  final int offset;

  bool get hasMore => offset + items.length < total;
}

class CatalogCompetitorOffer {
  CatalogCompetitorOffer({
    required this.observationId,
    required this.sellerId,
    required this.sellerName,
    required this.title,
    required this.url,
    required Object price,
    required this.currency,
    required this.isAvailable,
    required Object? normalizedPrice,
    required this.tier,
    required this.matchConfidence,
    required this.observedAt,
    this.automaticEligible = false,
    this.hardGateResult = 'MANUAL_REVIEW',
    this.oeVerificationStatus = 'UNKNOWN',
    this.reasonCodes = const [],
  }) : price = DecimalValue.from(price),
       normalizedPrice = DecimalValue.tryParse(normalizedPrice);

  factory CatalogCompetitorOffer.fromJson(Map<String, dynamic> json) {
    return CatalogCompetitorOffer(
      observationId: json['observation_id'] as String,
      sellerId: json['seller_id'] as String,
      sellerName: json['seller_name'] as String,
      title: json['title'] as String,
      url: json['url'] as String,
      price: json['price'] ?? 0,
      currency: json['currency'] as String,
      isAvailable: json['is_available'] as bool?,
      normalizedPrice: json['normalized_price'],
      tier: json['tier'] as String,
      matchConfidence: _decimal(json['match_confidence']) ?? 0,
      observedAt: DateTime.parse(json['observed_at'] as String),
      automaticEligible: json['automatic_eligible'] as bool? ?? false,
      hardGateResult: json['hard_gate_result'] as String? ?? 'MANUAL_REVIEW',
      oeVerificationStatus:
          json['oe_verification_status'] as String? ?? 'UNKNOWN',
      reasonCodes: (json['reason_codes'] as List<dynamic>? ?? const [])
          .map((item) => item.toString())
          .toList(growable: false),
    );
  }

  final String observationId;
  final String sellerId;
  final String sellerName;
  final String title;
  final String url;
  final DecimalValue price;
  final String currency;
  final bool? isAvailable;
  final DecimalValue? normalizedPrice;
  final String tier;
  final double matchConfidence;
  final DateTime observedAt;
  final bool automaticEligible;
  final String hardGateResult;
  final String oeVerificationStatus;
  final List<String> reasonCodes;
}

class CatalogDiscoveredOffer {
  CatalogDiscoveredOffer({
    required this.discoveryOfferId,
    required this.sourceListingId,
    required this.sellerId,
    required this.sellerName,
    required this.title,
    required this.url,
    required this.sku,
    this.mpn,
    this.oeRaw,
    this.partNumbers = const [],
    required this.brand,
    required Object salePrice,
    required Object? referencePrice,
    required this.currency,
    required this.measureUnit,
    required this.isAvailable,
    required this.titleContainsQuery,
    required this.identityStatus,
    required this.sourceConfidence,
    required this.reasonCodes,
    this.selectionStatus = 'REVIEW',
    this.selectionReason = 'LEGACY_UNCLASSIFIED',
    this.passedGates = const [],
    this.selectionFlags = const [],
    this.selectionDetails = const {},
    this.predictedTier = 'unknown',
    this.tierConfidence = 0,
  }) : salePrice = DecimalValue.from(salePrice),
       referencePrice = DecimalValue.tryParse(referencePrice);

  factory CatalogDiscoveredOffer.fromJson(Map<String, dynamic> json) {
    return CatalogDiscoveredOffer(
      discoveryOfferId: json['discovery_offer_id'] as String,
      sourceListingId: json['source_listing_id'] as String,
      sellerId: json['seller_id'] as String,
      sellerName: json['seller_name'] as String,
      title: json['title'] as String,
      url: json['url'] as String,
      sku: json['sku'] as String?,
      mpn: json['mpn'] as String?,
      oeRaw: json['oe_raw'] as String?,
      partNumbers: (json['part_numbers'] as List<dynamic>? ?? const [])
          .map((item) => item.toString())
          .toList(growable: false),
      brand: json['brand'] as String?,
      salePrice: json['sale_price'] ?? 0,
      referencePrice: json['reference_price'],
      currency: json['currency'] as String,
      measureUnit: json['measure_unit'] as String?,
      isAvailable: json['is_available'] as bool?,
      titleContainsQuery: json['title_contains_query'] as bool? ?? false,
      identityStatus: json['identity_status'] as String,
      sourceConfidence: _decimal(json['source_confidence']) ?? 0,
      reasonCodes: (json['reason_codes'] as List<dynamic>? ?? const [])
          .map((item) => item.toString())
          .toList(growable: false),
      selectionStatus: json['selection_status'] as String? ?? 'REVIEW',
      selectionReason:
          json['selection_reason'] as String? ?? 'LEGACY_UNCLASSIFIED',
      passedGates: (json['passed_gates'] as List<dynamic>? ?? const [])
          .map((item) => item.toString())
          .toList(growable: false),
      selectionFlags: (json['selection_flags'] as List<dynamic>? ?? const [])
          .map((item) => item.toString())
          .toList(growable: false),
      selectionDetails:
          (json['selection_details'] as Map<String, dynamic>?) ?? const {},
      predictedTier: json['predicted_tier'] as String? ?? 'unknown',
      tierConfidence: _decimal(json['tier_confidence']) ?? 0,
    );
  }

  final String discoveryOfferId;
  final String sourceListingId;
  final String sellerId;
  final String sellerName;
  final String title;
  final String url;
  final String? sku;
  final String? mpn;
  final String? oeRaw;
  final List<String> partNumbers;
  final String? brand;
  final DecimalValue salePrice;
  final DecimalValue? referencePrice;
  final String currency;
  final String? measureUnit;
  final bool? isAvailable;
  final bool titleContainsQuery;
  final String identityStatus;
  final double sourceConfidence;
  final List<String> reasonCodes;
  final String selectionStatus;
  final String selectionReason;
  final List<String> passedGates;
  final List<String> selectionFlags;
  final Map<String, dynamic> selectionDetails;
  final String predictedTier;
  final double tierConfidence;
}

class CatalogCompetitorComparison {
  CatalogCompetitorComparison({
    required this.recommendationId,
    required this.comparedAt,
    required Object? currentPrice,
    required Object? fairPrice,
    required Object? recommendedPrice,
    required this.currency,
    required this.reasonCodes,
    required this.items,
    this.discoveryRunId,
    this.discoveredAt,
    this.discoveryQuery,
    this.discoveryStatus,
    this.promReportedTotal,
    this.discoveredTotal = 0,
    this.discoveryRetrievedCount = 0,
    this.discoveryPersistedCount = 0,
    this.ownedExcludedCount = 0,
    this.discoveryRejectedCount = 0,
    this.pricingEvidenceCount = 0,
    this.referenceOnlyCount = 0,
    this.rejectedCandidateCount = 0,
    this.selectionHistogram = const {},
    this.searchPagesFetched = 0,
    this.searchPageLimit = 0,
    this.unfetchedCount = 0,
    this.coverageRatio,
    this.coverageReason,
    this.selectionMethodVersion,
    this.selectionConfigSha256,
    this.brandRulesDatasetId,
    this.confidenceGrade,
    this.dispersion,
    this.discoveryItems = const [],
    this.pricingEvidence = const [],
    this.referenceOnly = const [],
    this.candidateItems = const [],
    this.collectionStatus,
  }) : currentPrice = DecimalValue.tryParse(currentPrice),
       fairPrice = DecimalValue.tryParse(fairPrice),
       recommendedPrice = DecimalValue.tryParse(recommendedPrice);

  factory CatalogCompetitorComparison.fromJson(Map<String, dynamic> json) {
    return CatalogCompetitorComparison(
      recommendationId: json['recommendation_id'] as String?,
      comparedAt: json['compared_at'] == null
          ? null
          : DateTime.parse(json['compared_at'] as String),
      currentPrice: json['current_price'],
      fairPrice: json['fair_price'],
      recommendedPrice: json['recommended_price'],
      currency: json['currency'] as String?,
      reasonCodes: (json['reason_codes'] as List<dynamic>? ?? const [])
          .map((item) => item.toString())
          .toList(growable: false),
      items: (json['items'] as List<dynamic>? ?? const [])
          .map(
            (item) =>
                CatalogCompetitorOffer.fromJson(item as Map<String, dynamic>),
          )
          .toList(growable: false),
      discoveryRunId: json['discovery_run_id'] as String?,
      discoveredAt: json['discovered_at'] == null
          ? null
          : DateTime.parse(json['discovered_at'] as String),
      discoveryQuery: json['discovery_query'] as String?,
      discoveryStatus: json['discovery_status'] as String?,
      promReportedTotal: (json['prom_reported_total'] as num?)?.toInt(),
      discoveredTotal: (json['discovered_total'] as num?)?.toInt() ?? 0,
      discoveryRetrievedCount:
          (json['discovery_retrieved_count'] as num?)?.toInt() ?? 0,
      discoveryPersistedCount:
          (json['discovery_persisted_count'] as num?)?.toInt() ?? 0,
      ownedExcludedCount: (json['owned_excluded_count'] as num?)?.toInt() ?? 0,
      discoveryRejectedCount:
          (json['discovery_rejected_count'] as num?)?.toInt() ?? 0,
      pricingEvidenceCount:
          (json['pricing_evidence_count'] as num?)?.toInt() ?? 0,
      referenceOnlyCount: (json['reference_only_count'] as num?)?.toInt() ?? 0,
      rejectedCandidateCount:
          (json['rejected_candidate_count'] as num?)?.toInt() ?? 0,
      selectionHistogram:
          (json['selection_histogram'] as Map<String, dynamic>? ?? const {})
              .map((key, value) => MapEntry(key, (value as num).toInt())),
      searchPagesFetched: (json['search_pages_fetched'] as num?)?.toInt() ?? 0,
      searchPageLimit: (json['search_page_limit'] as num?)?.toInt() ?? 0,
      unfetchedCount: (json['unfetched_count'] as num?)?.toInt() ?? 0,
      confidenceGrade: json['confidence_grade'] as String?,
      dispersion: _decimal(json['dispersion']),
      coverageRatio: _decimal(json['coverage_ratio']),
      coverageReason: json['coverage_reason'] as String?,
      selectionMethodVersion: json['selection_method_version'] as String?,
      selectionConfigSha256: json['selection_config_sha256'] as String?,
      brandRulesDatasetId: json['brand_rules_dataset_id'] as String?,
      discoveryItems: (json['discovery_items'] as List<dynamic>? ?? const [])
          .map(
            (item) =>
                CatalogDiscoveredOffer.fromJson(item as Map<String, dynamic>),
          )
          .toList(growable: false),
      pricingEvidence: (json['pricing_evidence'] as List<dynamic>? ?? const [])
          .map(
            (item) =>
                CatalogDiscoveredOffer.fromJson(item as Map<String, dynamic>),
          )
          .toList(growable: false),
      referenceOnly: (json['reference_only'] as List<dynamic>? ?? const [])
          .map(
            (item) =>
                CatalogDiscoveredOffer.fromJson(item as Map<String, dynamic>),
          )
          .toList(growable: false),
      candidateItems: (json['candidate_items'] as List<dynamic>? ?? const [])
          .map(
            (item) =>
                CatalogCompetitorOffer.fromJson(item as Map<String, dynamic>),
          )
          .toList(growable: false),
      collectionStatus: json['collection_status'] as String?,
    );
  }

  final String? recommendationId;
  final DateTime? comparedAt;
  final DecimalValue? currentPrice;
  final DecimalValue? fairPrice;
  final DecimalValue? recommendedPrice;
  final String? currency;
  final List<String> reasonCodes;
  final List<CatalogCompetitorOffer> items;
  final String? discoveryRunId;
  final DateTime? discoveredAt;
  final String? discoveryQuery;
  final String? discoveryStatus;
  final int? promReportedTotal;
  final int discoveredTotal;
  final int discoveryRetrievedCount;
  final int discoveryPersistedCount;
  final int ownedExcludedCount;
  final int discoveryRejectedCount;
  final int pricingEvidenceCount;
  final int referenceOnlyCount;
  final int rejectedCandidateCount;
  final Map<String, int> selectionHistogram;
  final int searchPagesFetched;
  final int searchPageLimit;
  final int unfetchedCount;
  final double? coverageRatio;
  final String? coverageReason;
  final String? selectionMethodVersion;
  final String? selectionConfigSha256;
  final String? brandRulesDatasetId;
  final String? confidenceGrade;
  final double? dispersion;
  final List<CatalogDiscoveredOffer> discoveryItems;

  /// Kept for the discovery API shape; discovery rows never enter pricing.
  final List<CatalogDiscoveredOffer> pricingEvidence;

  /// Same part, level unknown or unconvertible: shown, never priced against.
  final List<CatalogDiscoveredOffer> referenceOnly;
  final List<CatalogCompetitorOffer> candidateItems;
  final String? collectionStatus;

  bool get hasComparison => recommendationId != null;
  bool get hasDiscovery => discoveryRunId != null;
}

double? _decimal(dynamic value) {
  if (value == null) return null;
  return double.tryParse(value.toString());
}
