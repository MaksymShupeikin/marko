/// Sorting offered in the catalog toolbar. The value goes to the API as-is.
enum ProductSort {
  name('name', 'За назвою'),
  priceAsc('price_asc', 'Спочатку дешевші'),
  priceDesc('price_desc', 'Спочатку дорожчі'),
  updated('updated', 'Нещодавно оновлені');

  const ProductSort(this.value, this.label);

  final String value;
  final String label;
}

class StoreProduct {
  const StoreProduct({
    required this.id,
    required this.name,
    required this.url,
    required this.sku,
    required this.brand,
    required this.price,
    required this.currency,
    required this.isAvailable,
    required this.imageUrl,
    this.storeName,
    this.marketplace = '',
    this.oemNumbers = const [],
    this.lastSeenAt,
  });

  factory StoreProduct.fromJson(Map<String, dynamic> json) {
    final rawPrice = json['current_price'];
    return StoreProduct(
      id: json['id'] as String,
      name: json['name'] as String,
      url: json['url'] as String,
      sku: json['sku'] as String?,
      brand: json['brand'] as String?,
      price: rawPrice == null ? null : double.tryParse(rawPrice.toString()),
      currency: json['currency'] as String,
      isAvailable: json['is_available'] as bool?,
      imageUrl: json['image_url'] as String?,
      storeName: json['store_name'] as String?,
      marketplace: json['marketplace'] as String? ?? '',
      oemNumbers: (json['oem_numbers'] as List<dynamic>? ?? const [])
          .map((value) => value.toString())
          .toList(growable: false),
      lastSeenAt: DateTime.tryParse(json['last_seen_at'] as String? ?? ''),
    );
  }

  final String id;
  final String name;
  final String url;
  final String? sku;
  final String? brand;
  final double? price;
  final String currency;
  final bool? isAvailable;
  final String? imageUrl;
  final String? storeName;
  final String marketplace;
  final List<String> oemNumbers;
  final DateTime? lastSeenAt;

  bool get isFromProm => url.contains('prom.ua');

  /// The number to look up on avto.pro: the richest one we know about.
  String? get primaryOem => oemNumbers.isNotEmpty ? oemNumbers.first : sku;

  String get availabilityLabel => switch (isAvailable) {
    true => 'В наявності',
    false => 'Немає в наявності',
    _ => 'Наявність невідома',
  };

  String get details => [
    brand,
    if (sku != null) 'SKU $sku',
    isAvailable == true ? 'В наявності' : 'Немає в наявності',
  ].whereType<String>().join(' · ');

  String get priceLabel => price == null
      ? 'Ціна не вказана'
      : '${price!.toStringAsFixed(2)} $currency';
}

typedef Product = StoreProduct;

class CatalogPage {
  const CatalogPage({required this.items, required this.total});

  factory CatalogPage.fromJson(Map<String, dynamic> json) {
    return CatalogPage(
      items: (json['items'] as List<dynamic>)
          .map((item) => StoreProduct.fromJson(item as Map<String, dynamic>))
          .toList(growable: false),
      total: (json['total'] as num).toInt(),
    );
  }

  final List<StoreProduct> items;
  final int total;

  bool get hasMore => items.length < total;
}

class CatalogState {
  const CatalogState({
    required this.page,
    this.query = '',
    this.sort = ProductSort.name,
    this.priceMin,
    this.priceMax,
    this.isLoadingMore = false,
    this.isRefreshing = false,
    this.selected,
    this.error,
  });

  final CatalogPage page;
  final String query;
  final ProductSort sort;
  final double? priceMin;
  final double? priceMax;
  final bool isLoadingMore;
  final bool isRefreshing;
  final StoreProduct? selected;
  final String? error;

  /// Nothing imported yet, as opposed to a search or a filter that found
  /// nothing: only then is the whole catalog UI pointless.
  bool get isPristineEmpty =>
      page.items.isEmpty &&
      query.trim().isEmpty &&
      priceMin == null &&
      priceMax == null;

  CatalogState copyWith({
    CatalogPage? page,
    String? query,
    ProductSort? sort,
    (double?, double?)? price,
    bool? isLoadingMore,
    bool? isRefreshing,
    StoreProduct? selected,
    String? error,
    bool clearSelected = false,
    bool clearError = false,
  }) {
    return CatalogState(
      page: page ?? this.page,
      query: query ?? this.query,
      sort: sort ?? this.sort,
      priceMin: price != null ? price.$1 : priceMin,
      priceMax: price != null ? price.$2 : priceMax,
      isLoadingMore: isLoadingMore ?? this.isLoadingMore,
      isRefreshing: isRefreshing ?? this.isRefreshing,
      selected: clearSelected ? null : selected ?? this.selected,
      error: clearError ? null : error ?? this.error,
    );
  }
}

class FileImportResult {
  const FileImportResult({
    required this.storeId,
    required this.storeName,
    required this.imported,
    required this.skipped,
  });

  factory FileImportResult.fromJson(Map<String, dynamic> json) {
    return FileImportResult(
      storeId: json['store_id'] as String,
      storeName: json['store_name'] as String,
      imported: (json['imported'] as num).toInt(),
      skipped: (json['skipped'] as num).toInt(),
    );
  }

  final String storeId;
  final String storeName;
  final int imported;
  final int skipped;

  String get summary =>
      'Магазин «$storeName»: завантажено $imported товарів'
      '${skipped > 0 ? ', пропущено $skipped' : ''}.';
}

class StoreSync {
  const StoreSync({
    required this.storeId,
    required this.syncRunId,
    required this.status,
  });

  factory StoreSync.fromJson(Map<String, dynamic> json) {
    return StoreSync(
      storeId: json['store_id'] as String,
      syncRunId: json['sync_run_id'] as String,
      status: json['status'] as String,
    );
  }

  final String storeId;
  final String syncRunId;
  final String status;
}

class SyncRun {
  const SyncRun({
    required this.status,
    required this.progressCurrent,
    required this.progressTotal,
    required this.error,
  });

  factory SyncRun.fromJson(Map<String, dynamic> json) {
    return SyncRun(
      status: json['status'] as String,
      progressCurrent: (json['progress_current'] as num).toInt(),
      progressTotal: (json['progress_total'] as num?)?.toInt(),
      error: json['error'] as String?,
    );
  }

  final String status;
  final int progressCurrent;
  final int? progressTotal;
  final String? error;

  bool get isFinished => status == 'completed' || status == 'failed';

  String get statusLabel => switch (status) {
    'queued' => 'в черзі',
    'running' => 'виконується',
    'completed' => 'готово',
    'failed' => 'помилка',
    _ => status,
  };

  double? get progress {
    final total = progressTotal;
    if (total != null && total > 0) return progressCurrent / total;
    return status == 'completed' ? 1 : null;
  }
}

class CompetitorOffer {
  const CompetitorOffer({
    required this.maker,
    required this.code,
    required this.city,
    required this.price,
    required this.currency,
    required this.boosted,
  });

  factory CompetitorOffer.fromJson(Map<String, dynamic> json) {
    return CompetitorOffer(
      maker: json['maker'] as String?,
      code: json['code'] as String?,
      city: json['city'] as String?,
      price: (json['price'] as num).toDouble(),
      currency: json['currency'] as String,
      boosted: json['boosted'] as bool,
    );
  }

  final String? maker;
  final String? code;
  final String? city;
  final double price;
  final String currency;
  final bool boosted;

  String get partLabel =>
      [maker, code].whereType<String>().join(' ').trim().isEmpty
      ? 'Без назви'
      : [maker, code].whereType<String>().join(' ');

  String get priceLabel => '${price.toStringAsFixed(2)} $currency';
}

class CompetitorSearch {
  const CompetitorSearch({
    required this.query,
    required this.title,
    required this.isOriginal,
    required this.partUrl,
    required this.offersTotal,
    required this.minPrice,
    required this.medianPrice,
    required this.maxPrice,
    required this.offers,
  });

  factory CompetitorSearch.fromJson(Map<String, dynamic> json) {
    return CompetitorSearch(
      query: json['query'] as String,
      title: json['title'] as String,
      isOriginal: json['is_original'] as bool,
      partUrl: json['part_url'] as String,
      offersTotal: (json['offers_total'] as num).toInt(),
      minPrice: (json['min_price'] as num?)?.toDouble(),
      medianPrice: (json['median_price'] as num?)?.toDouble(),
      maxPrice: (json['max_price'] as num?)?.toDouble(),
      offers: (json['offers'] as List<dynamic>)
          .map((item) => CompetitorOffer.fromJson(item as Map<String, dynamic>))
          .toList(growable: false),
    );
  }

  final String query;
  final String title;
  final bool isOriginal;
  final String partUrl;
  final int offersTotal;
  final double? minPrice;
  final double? medianPrice;
  final double? maxPrice;
  final List<CompetitorOffer> offers;
}

class CatalogImportState {
  const CatalogImportState({
    this.isSubmitting = false,
    this.activeSync,
    this.activeJob,
    this.error,
    this.lastImport,
  });

  final bool isSubmitting;
  final StoreSync? activeSync;
  final SyncRun? activeJob;
  final String? error;
  final FileImportResult? lastImport;

  bool get hasActiveJob => activeSync != null && activeJob?.isFinished != true;

  CatalogImportState copyWith({
    bool? isSubmitting,
    StoreSync? activeSync,
    SyncRun? activeJob,
    String? error,
    FileImportResult? lastImport,
    bool clearJob = false,
    bool clearError = false,
    bool clearImport = false,
  }) {
    return CatalogImportState(
      isSubmitting: isSubmitting ?? this.isSubmitting,
      activeSync: activeSync ?? this.activeSync,
      activeJob: clearJob ? null : activeJob ?? this.activeJob,
      error: clearError ? null : error ?? this.error,
      lastImport: clearImport ? null : lastImport ?? this.lastImport,
    );
  }
}
