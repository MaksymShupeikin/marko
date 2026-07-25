class CatalogStorePresence {
  const CatalogStorePresence({
    required this.storeId,
    required this.externalId,
    required this.name,
    required this.url,
    required this.listingUrl,
    required this.listingCount,
    required this.price,
    required this.currency,
    required this.isAvailable,
  });

  factory CatalogStorePresence.fromJson(Map<String, dynamic> json) {
    return CatalogStorePresence(
      storeId: json['store_id'] as String,
      externalId: json['external_id'] as String,
      name: json['name'] as String,
      url: json['url'] as String,
      listingUrl: json['listing_url'] as String,
      listingCount: (json['listing_count'] as num).toInt(),
      price: _decimal(json['price']),
      currency: json['currency'] as String,
      isAvailable: json['is_available'] as bool?,
    );
  }

  final String storeId;
  final String externalId;
  final String name;
  final String url;
  final String listingUrl;
  final int listingCount;
  final double? price;
  final String currency;
  final bool? isAvailable;

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
  static const primaryStoreExternalId = '2847093';

  const CatalogProduct({
    required this.id,
    required this.identityKind,
    required this.name,
    required this.sku,
    required this.oe,
    required this.modelId,
    required this.brand,
    required this.imageUrl,
    required this.priceMin,
    required this.priceMax,
    required this.currency,
    required this.listingCount,
    required this.stores,
    this.recommendedPrice,
    this.recommendationCurrency,
    this.recommendationAction,
    this.recommendationComputedAt,
  });

  factory CatalogProduct.fromJson(Map<String, dynamic> json) {
    return CatalogProduct(
      id: json['id'] as String,
      identityKind: json['identity_kind'] as String,
      name: json['name'] as String,
      sku: json['sku'] as String?,
      oe: json['oe'] as String?,
      modelId: json['model_id'] as String?,
      brand: json['brand'] as String?,
      imageUrl: json['image_url'] as String?,
      priceMin: _decimal(json['price_min']),
      priceMax: _decimal(json['price_max']),
      currency: json['currency'] as String?,
      listingCount: (json['listing_count'] as num).toInt(),
      stores: (json['stores'] as List<dynamic>)
          .map(
            (item) =>
                CatalogStorePresence.fromJson(item as Map<String, dynamic>),
          )
          .toList(growable: false),
      recommendedPrice: _decimal(json['recommended_price']),
      recommendationCurrency: json['recommendation_currency'] as String?,
      recommendationAction: json['recommendation_action'] as String?,
      recommendationComputedAt: json['recommendation_computed_at'] == null
          ? null
          : DateTime.parse(json['recommendation_computed_at'] as String),
    );
  }

  final String id;
  final String identityKind;
  final String name;
  final String? sku;
  final String? oe;
  final String? modelId;
  final String? brand;
  final String? imageUrl;
  final double? priceMin;
  final double? priceMax;
  final String? currency;
  final int listingCount;
  final List<CatalogStorePresence> stores;
  final double? recommendedPrice;
  final String? recommendationCurrency;
  final String? recommendationAction;
  final DateTime? recommendationComputedAt;

  bool get isDuplicate => listingCount > 1;
  bool get isInMultipleStores => stores.length > 1;
  bool get hasRaiseRecommendation =>
      recommendationAction == 'RAISE' && recommendedPrice != null;
  bool get hasLowerRecommendation =>
      recommendationAction == 'LOWER' && recommendedPrice != null;

  CatalogStorePresence? get primaryStore {
    for (final store in stores) {
      if (store.externalId == primaryStoreExternalId) return store;
    }
    return stores.isEmpty ? null : stores.first;
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
    );
  }

  final List<CatalogProduct> items;
  final int total;
  final int catalogTotal;
  final int listingTotal;
  final int duplicatesRemoved;
  final int storeTotal;
  final List<CatalogStoreOption> stores;

  bool get hasMore => items.length < total;
}

class CatalogCompetitorOffer {
  const CatalogCompetitorOffer({
    required this.observationId,
    required this.sellerId,
    required this.sellerName,
    required this.title,
    required this.url,
    required this.price,
    required this.currency,
    required this.isAvailable,
    required this.normalizedPrice,
    required this.tier,
    required this.matchConfidence,
    required this.observedAt,
  });

  factory CatalogCompetitorOffer.fromJson(Map<String, dynamic> json) {
    return CatalogCompetitorOffer(
      observationId: json['observation_id'] as String,
      sellerId: json['seller_id'] as String,
      sellerName: json['seller_name'] as String,
      title: json['title'] as String,
      url: json['url'] as String,
      price: _decimal(json['price']) ?? 0,
      currency: json['currency'] as String,
      isAvailable: json['is_available'] as bool?,
      normalizedPrice: _decimal(json['normalized_price']),
      tier: json['tier'] as String,
      matchConfidence: _decimal(json['match_confidence']) ?? 0,
      observedAt: DateTime.parse(json['observed_at'] as String),
    );
  }

  final String observationId;
  final String sellerId;
  final String sellerName;
  final String title;
  final String url;
  final double price;
  final String currency;
  final bool? isAvailable;
  final double? normalizedPrice;
  final String tier;
  final double matchConfidence;
  final DateTime observedAt;
}

class CatalogCompetitorComparison {
  const CatalogCompetitorComparison({
    required this.recommendationId,
    required this.comparedAt,
    required this.currentPrice,
    required this.fairPrice,
    required this.recommendedPrice,
    required this.currency,
    required this.reasonCodes,
    required this.items,
  });

  factory CatalogCompetitorComparison.fromJson(Map<String, dynamic> json) {
    return CatalogCompetitorComparison(
      recommendationId: json['recommendation_id'] as String?,
      comparedAt: json['compared_at'] == null
          ? null
          : DateTime.parse(json['compared_at'] as String),
      currentPrice: _decimal(json['current_price']),
      fairPrice: _decimal(json['fair_price']),
      recommendedPrice: _decimal(json['recommended_price']),
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
    );
  }

  final String? recommendationId;
  final DateTime? comparedAt;
  final double? currentPrice;
  final double? fairPrice;
  final double? recommendedPrice;
  final String? currency;
  final List<String> reasonCodes;
  final List<CatalogCompetitorOffer> items;

  bool get hasComparison => recommendationId != null;
}

double? _decimal(dynamic value) {
  if (value == null) return null;
  return double.tryParse(value.toString());
}
