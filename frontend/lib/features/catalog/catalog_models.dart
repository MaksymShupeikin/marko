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

  bool get isDuplicate => listingCount > 1;
  bool get isInMultipleStores => stores.length > 1;

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
    );
  }

  final List<CatalogProduct> items;
  final int total;
  final int catalogTotal;
  final int listingTotal;
  final int duplicatesRemoved;
  final int storeTotal;

  bool get hasMore => items.length < total;
}

double? _decimal(dynamic value) {
  if (value == null) return null;
  return double.tryParse(value.toString());
}
