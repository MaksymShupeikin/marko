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

/// Where a product came from: an uploaded XLSX export or a Prom scrape.
enum ProductSource {
  all(null, 'Усі'),
  export('export', 'З файлу'),
  scrape('scrape', 'З Prom');

  const ProductSource(this.value, this.label);

  final String? value;
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
    this.canManage = false,
    this.source = ProductSource.scrape,
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
      canManage: json['can_manage'] as bool? ?? false,
      source: json['source'] == 'export'
          ? ProductSource.export
          : ProductSource.scrape,
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
  final bool canManage;
  final ProductSource source;

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

class ProductUpdate {
  const ProductUpdate({
    required this.name,
    required this.sku,
    required this.brand,
    required this.price,
    required this.isAvailable,
    required this.imageUrl,
    required this.oemNumbers,
  });

  final String name;
  final String? sku;
  final String? brand;
  final double? price;
  final bool? isAvailable;
  final String? imageUrl;
  final List<String> oemNumbers;

  Map<String, dynamic> toJson() => {
    'name': name,
    'sku': sku,
    'brand': brand,
    'current_price': price,
    'is_available': isAvailable,
    'image_url': imageUrl,
    'oem_numbers': oemNumbers,
  };
}

typedef Product = StoreProduct;

/// One connected store from which the catalog was imported.
class StoreInfo {
  const StoreInfo({
    required this.id,
    required this.name,
    required this.url,
    required this.productCount,
    this.fileProductCount = 0,
    this.logoUrl,
  });

  factory StoreInfo.fromJson(Map<String, dynamic> json) {
    return StoreInfo(
      id: json['id'] as String,
      name: json['name'] as String? ?? '',
      url: json['url'] as String? ?? '',
      productCount: (json['product_count'] as num?)?.toInt() ?? 0,
      fileProductCount: (json['file_product_count'] as num?)?.toInt() ?? 0,
      logoUrl: json['logo_url'] as String?,
    );
  }

  final String id;
  final String name;
  final String url;
  final int productCount;
  final int fileProductCount;
  final String? logoUrl;

  String get productCountLabel {
    final n = productCount;
    final mod10 = n % 10, mod100 = n % 100;
    final word = (mod10 == 1 && mod100 != 11)
        ? 'товар'
        : (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14))
        ? 'товари'
        : 'товарів';
    return '$n $word';
  }
}

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
    this.selectedIds = const {},
    this.allMatchingSelected = false,
    this.bulkJob,
    this.source = ProductSource.all,
    this.storeIds = const {},
    this.hasImportedProducts = false,
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

  /// Ticked cards, for actions applied to many products at once.
  final Set<String> selectedIds;

  /// The selection is the whole filtered catalog, not the ticked cards —
  /// actions then run server-side over the filter instead of per id.
  final bool allMatchingSelected;

  /// Progress of a running catalog-wide refresh.
  final SyncRun? bulkJob;
  final ProductSource source;

  /// Ticked store cards above the catalog; empty — every store.
  final Set<String> storeIds;
  final bool hasImportedProducts;
  final String? error;

  /// How many products the buttons would act on right now.
  int get actionCount =>
      allMatchingSelected ? page.total : selectedIds.length;

  bool get hasSelection => allMatchingSelected || selectedIds.isNotEmpty;

  /// Whether any search query, price bounds, or source filter is currently applied.
  bool get hasActiveFilters =>
      query.trim().isNotEmpty ||
      priceMin != null ||
      priceMax != null ||
      source != ProductSource.all ||
      storeIds.isNotEmpty;

  /// Nothing imported yet, as opposed to a search or a filter that found
  /// nothing: only then is the whole catalog UI pointless.
  bool get isPristineEmpty =>
      !hasImportedProducts && page.items.isEmpty && !hasActiveFilters;

  CatalogState copyWith({
    CatalogPage? page,
    String? query,
    ProductSort? sort,
    (double?, double?)? price,
    bool? isLoadingMore,
    bool? isRefreshing,
    StoreProduct? selected,
    Set<String>? selectedIds,
    bool? allMatchingSelected,
    SyncRun? bulkJob,
    ProductSource? source,
    Set<String>? storeIds,
    bool? hasImportedProducts,
    String? error,
    bool clearSelected = false,
    bool clearError = false,
    bool clearBulkJob = false,
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
      selectedIds: selectedIds ?? this.selectedIds,
      allMatchingSelected: allMatchingSelected ?? this.allMatchingSelected,
      bulkJob: clearBulkJob ? null : bulkJob ?? this.bulkJob,
      source: source ?? this.source,
      storeIds: storeIds ?? this.storeIds,
      hasImportedProducts: hasImportedProducts ?? this.hasImportedProducts,
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
      storeId: json['store_id'] as String?,
      syncRunId: json['sync_run_id'] as String,
      status: json['status'] as String,
    );
  }

  /// Null for catalog-wide work, which belongs to no single store.
  final String? storeId;
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

  bool get isFinished =>
      status == 'completed' || status == 'failed' || status == 'cancelled';

  String get statusLabel => switch (status) {
    'queued' => 'в черзі',
    'running' => 'виконується',
    'completed' => 'готово',
    'failed' => 'помилка',
    'cancelled' => 'скасовано',
    _ => status,
  };

  double? get progress {
    final total = progressTotal;
    if (total != null && total > 0) return progressCurrent / total;
    return status == 'completed' ? 1 : null;
  }
}

/// Один магазин у черзі імпорту: сам запуск плюс те, чим його підписати.
class ActiveSyncRun {
  const ActiveSyncRun({
    required this.syncRunId,
    required this.storeId,
    required this.storeName,
    required this.storeLogoUrl,
    required this.run,
  });

  factory ActiveSyncRun.fromJson(Map<String, dynamic> json) {
    return ActiveSyncRun(
      syncRunId: json['id'] as String,
      storeId: json['store_id'] as String?,
      storeName: json['store_name'] as String?,
      storeLogoUrl: json['store_logo_url'] as String?,
      run: SyncRun.fromJson(json),
    );
  }

  final String syncRunId;
  final String? storeId;
  final String? storeName;
  final String? storeLogoUrl;
  final SyncRun run;

  /// Той самий магазин із оновленим станом запуску — для підсумку в кінці.
  ActiveSyncRun withRun(SyncRun value) => ActiveSyncRun(
    syncRunId: syncRunId,
    storeId: storeId,
    storeName: storeName,
    storeLogoUrl: storeLogoUrl,
    run: value,
  );

  /// Виконується прямо зараз — на відміну від тих, хто чекає черги.
  bool get isRunning => run.status == 'running';
  String get title => storeName?.trim().isNotEmpty == true
      ? storeName!.trim()
      : 'Магазин';
}

class MarketPriceOffer {
  const MarketPriceOffer({
    required this.source,
    required this.title,
    required this.price,
    required this.currency,
    required this.url,
    this.seller,
    this.city,
    this.availability,
    this.condition,
    this.imageUrl,
    this.confidence = 1,
    this.isAnalog = false,
  });

  factory MarketPriceOffer.fromJson(Map<String, dynamic> json) {
    final rawPrice = json['price'];
    return MarketPriceOffer(
      source: json['source'] as String,
      title: json['title'] as String,
      price: rawPrice == null ? 0 : double.tryParse(rawPrice.toString()) ?? 0,
      currency: json['currency'] as String,
      url: json['url'] as String,
      seller: json['seller'] as String?,
      city: json['city'] as String?,
      availability: json['availability'] as String?,
      condition: json['condition'] as String?,
      imageUrl: json['image_url'] as String?,
      confidence: (json['confidence'] as num?)?.toDouble() ?? 1,
      isAnalog: json['is_analog'] as bool? ?? false,
    );
  }

  final String source;
  final String title;
  final double price;
  final String currency;
  final String url;
  final String? seller;
  final String? city;
  final String? availability;
  final String? condition;
  final String? imageUrl;
  final double confidence;

  /// Не той самий номер: аналог іншого виробника або схожа позиція.
  final bool isAnalog;

  String get priceLabel => '${price.toStringAsFixed(0)} $currency';

  String get subtitle => [
    seller,
    city,
    condition == 'used'
        ? 'б/в'
        : condition == 'new'
        ? 'нове'
        : null,
  ].whereType<String>().join(' · ');
}

class SourcePriceResult {
  const SourcePriceResult({
    required this.source,
    required this.label,
    required this.status,
    required this.offersTotal,
    required this.offers,
    this.error,
    this.minPrice,
    this.medianPrice,
    this.maxPrice,
  });

  factory SourcePriceResult.fromJson(Map<String, dynamic> json) {
    double? price(String key) {
      final value = json[key];
      return value == null ? null : double.tryParse(value.toString());
    }

    return SourcePriceResult(
      source: json['source'] as String,
      label: json['label'] as String,
      status: json['status'] as String,
      error: json['error'] as String?,
      offersTotal: (json['offers_total'] as num).toInt(),
      minPrice: price('min_price'),
      medianPrice: price('median_price'),
      maxPrice: price('max_price'),
      offers: (json['offers'] as List<dynamic>? ?? const [])
          .map(
            (item) => MarketPriceOffer.fromJson(item as Map<String, dynamic>),
          )
          .toList(growable: false),
    );
  }

  final String source;
  final String label;
  final String status;
  final String? error;
  final int offersTotal;
  final double? minPrice;
  final double? medianPrice;
  final double? maxPrice;
  final List<MarketPriceOffer> offers;

  bool get hasOffers => offers.isNotEmpty;
}

class CompetitorPriceStats {
  const CompetitorPriceStats({
    required this.offersTotal,
    required this.sourcesTotal,
    this.minPrice,
    this.medianPrice,
    this.maxPrice,
    this.recommendedPrice,
  });

  factory CompetitorPriceStats.fromJson(Map<String, dynamic> json) {
    double? price(String key) {
      final value = json[key];
      return value == null ? null : double.tryParse(value.toString());
    }

    return CompetitorPriceStats(
      offersTotal: (json['offers_total'] as num).toInt(),
      sourcesTotal: (json['sources_total'] as num).toInt(),
      minPrice: price('min_price'),
      medianPrice: price('median_price'),
      maxPrice: price('max_price'),
      recommendedPrice: price('recommended_price'),
    );
  }

  final int offersTotal;
  final int sourcesTotal;
  final double? minPrice;
  final double? medianPrice;
  final double? maxPrice;

  /// Конкретна сума до виставлення: трохи нижче мінімуму конкурентів.
  final double? recommendedPrice;
}

class CompetitorPriceReport {
  const CompetitorPriceReport({
    required this.cached,
    required this.observedAt,
    required this.stats,
    required this.sources,
  });

  factory CompetitorPriceReport.fromJson(Map<String, dynamic> json) {
    return CompetitorPriceReport(
      cached: json['cached'] as bool? ?? false,
      observedAt: DateTime.tryParse(json['observed_at'] as String? ?? ''),
      stats: CompetitorPriceStats.fromJson(
        json['stats'] as Map<String, dynamic>,
      ),
      sources: (json['sources'] as List<dynamic>)
          .map(
            (item) => SourcePriceResult.fromJson(item as Map<String, dynamic>),
          )
          .toList(growable: false),
    );
  }

  final bool cached;
  final DateTime? observedAt;
  final CompetitorPriceStats stats;
  final List<SourcePriceResult> sources;

  String get currency {
    for (final source in sources) {
      if (source.offers.isNotEmpty) return source.offers.first.currency;
    }
    return 'UAH';
  }
}

enum ImportSubmittingType {
  none,
  file,
  prom,
}

class CatalogImportState {
  const CatalogImportState({
    this.submittingType = ImportSubmittingType.none,
    this.runs = const [],
    this.finished,
    this.error,
    this.lastImport,
  });

  final ImportSubmittingType submittingType;

  /// Черга імпортів у порядку виконання: перший вантажиться, решта чекає.
  final List<ActiveSyncRun> runs;

  /// Щойно завершений запуск — його ще кілька секунд показуємо з галочкою.
  final ActiveSyncRun? finished;
  final String? error;
  final FileImportResult? lastImport;

  bool get isSubmitting => submittingType != ImportSubmittingType.none;
  bool get isSubmittingFile => submittingType == ImportSubmittingType.file;
  bool get isSubmittingProm => submittingType == ImportSubmittingType.prom;
  bool get hasActiveJob => runs.isNotEmpty;

  /// Що показує капсула: жива черга, а коли її нема — підсумок останнього.
  List<ActiveSyncRun> get visibleRuns {
    if (runs.isNotEmpty) return runs;
    final done = finished;
    return done == null ? const [] : [done];
  }

  int get queuedCount => runs.where((run) => !run.isRunning).length;

  CatalogImportState copyWith({
    ImportSubmittingType? submittingType,
    List<ActiveSyncRun>? runs,
    ActiveSyncRun? finished,
    String? error,
    FileImportResult? lastImport,
    bool clearFinished = false,
    bool clearError = false,
    bool clearImport = false,
  }) {
    return CatalogImportState(
      submittingType: submittingType ?? this.submittingType,
      runs: runs ?? this.runs,
      finished: clearFinished ? null : finished ?? this.finished,
      error: clearError ? null : error ?? this.error,
      lastImport: clearImport ? null : lastImport ?? this.lastImport,
    );
  }
}

