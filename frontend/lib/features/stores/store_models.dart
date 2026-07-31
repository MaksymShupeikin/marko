import '../../core/presentation_formatters.dart';

DateTime? _optionalDate(dynamic value) =>
    value == null ? null : DateTime.tryParse(value.toString());

double? _optionalDecimal(dynamic value) =>
    value == null ? null : double.tryParse(value.toString());

class StoreSummary {
  const StoreSummary({
    required this.id,
    required this.externalId,
    required this.name,
    required this.url,
    required this.kind,
    required this.productCount,
    required this.lastSyncedAt,
  });

  factory StoreSummary.fromJson(Map<String, dynamic> json) {
    return StoreSummary(
      id: json['id'] as String,
      externalId: json['external_id'] as String,
      name: json['name'] as String?,
      url: json['url'] as String,
      kind: json['kind'] as String,
      productCount: (json['product_count'] as num).toInt(),
      lastSyncedAt: DateTime.tryParse(json['last_synced_at'] as String? ?? ''),
    );
  }

  final String id;
  final String externalId;
  final String? name;
  final String url;
  final String kind;
  final int productCount;
  final DateTime? lastSyncedAt;

  String get displayName => name ?? 'Prom store $externalId';

  String get syncDescription {
    final value = lastSyncedAt;
    if (value == null) return 'ещё не синхронизирован';
    return 'обновлён ${formatLocalDateTime(value)}';
  }
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
    this.id,
    this.workspaceId,
    this.storeId,
    this.kind,
    this.scrapeItemVersion,
    this.scrapeState,
    this.deduplicatedSubmissions = 0,
    this.taskExecutions = 0,
    this.taskRedeliveries = 0,
    this.maxTaskExecutions = 0,
    this.deadlineAt,
    this.ownerTaskId,
    this.leaseExpiresAt,
    this.checkpoint,
    this.catalogPages = 0,
    this.productsExtracted = 0,
    this.productsPersisted = 0,
    this.duplicateProducts = 0,
    this.databaseWrites = 0,
    this.rawEvidenceBytes = 0,
    this.structuredCompleteness,
    this.evidenceCoverage,
    this.startedAt,
    this.finishedAt,
    this.createdAt,
  });

  factory SyncRun.fromJson(Map<String, dynamic> json) {
    return SyncRun(
      status: json['status'] as String,
      progressCurrent: (json['progress_current'] as num).toInt(),
      progressTotal: (json['progress_total'] as num?)?.toInt(),
      error: json['error'] as String?,
      id: json['id']?.toString(),
      workspaceId: json['workspace_id']?.toString(),
      storeId: json['store_id']?.toString(),
      kind: json['kind']?.toString(),
      scrapeItemVersion: json['scrape_item_version']?.toString(),
      scrapeState: json['scrape_state']?.toString(),
      deduplicatedSubmissions:
          (json['scrape_deduplicated_submissions'] as num?)?.toInt() ?? 0,
      taskExecutions: (json['scrape_task_executions'] as num?)?.toInt() ?? 0,
      taskRedeliveries:
          (json['scrape_task_redeliveries'] as num?)?.toInt() ?? 0,
      maxTaskExecutions:
          (json['scrape_max_task_executions'] as num?)?.toInt() ?? 0,
      deadlineAt: _optionalDate(json['scrape_deadline_at']),
      ownerTaskId: json['scrape_owner_task_id']?.toString(),
      leaseExpiresAt: _optionalDate(json['scrape_lease_expires_at']),
      checkpoint: json['scrape_checkpoint'] is Map
          ? Map<String, dynamic>.from(json['scrape_checkpoint'] as Map)
          : null,
      catalogPages: (json['scrape_catalog_pages'] as num?)?.toInt() ?? 0,
      productsExtracted:
          (json['scrape_products_extracted'] as num?)?.toInt() ?? 0,
      productsPersisted:
          (json['scrape_products_persisted'] as num?)?.toInt() ?? 0,
      duplicateProducts:
          (json['scrape_duplicate_products'] as num?)?.toInt() ?? 0,
      databaseWrites: (json['scrape_database_writes'] as num?)?.toInt() ?? 0,
      rawEvidenceBytes:
          (json['scrape_raw_evidence_bytes'] as num?)?.toInt() ?? 0,
      structuredCompleteness: _optionalDecimal(
        json['scrape_structured_completeness'],
      ),
      evidenceCoverage: _optionalDecimal(json['scrape_evidence_coverage']),
      startedAt: _optionalDate(json['started_at']),
      finishedAt: _optionalDate(json['finished_at']),
      createdAt: _optionalDate(json['created_at']),
    );
  }

  final String status;
  final int progressCurrent;
  final int? progressTotal;
  final String? error;
  final String? id;
  final String? workspaceId;
  final String? storeId;
  final String? kind;
  final String? scrapeItemVersion;
  final String? scrapeState;
  final int deduplicatedSubmissions;
  final int taskExecutions;
  final int taskRedeliveries;
  final int maxTaskExecutions;
  final DateTime? deadlineAt;
  final String? ownerTaskId;
  final DateTime? leaseExpiresAt;
  final Map<String, dynamic>? checkpoint;
  final int catalogPages;
  final int productsExtracted;
  final int productsPersisted;
  final int duplicateProducts;
  final int databaseWrites;
  final int rawEvidenceBytes;
  final double? structuredCompleteness;
  final double? evidenceCoverage;
  final DateTime? startedAt;
  final DateTime? finishedAt;
  final DateTime? createdAt;

  bool get isFinished =>
      status == 'completed' ||
      status == 'failed' ||
      status == 'monitoring_failed';

  String get statusLabel => switch (status) {
    'queued' => 'в очереди',
    'running' => 'выполняется',
    'completed' => 'готово',
    'failed' => 'ошибка',
    'monitoring_failed' => 'слежение остановлено',
    _ => status,
  };

  double? get progress {
    final total = progressTotal;
    if (total != null && total > 0) return progressCurrent / total;
    return status == 'completed' ? 1 : null;
  }
}

class StoreProduct {
  StoreProduct({
    required this.id,
    required this.name,
    required this.url,
    required this.sku,
    required this.brand,
    required Object? price,
    required this.currency,
    required this.isAvailable,
    required this.imageUrl,
  }) : price = DecimalValue.tryParse(price);

  factory StoreProduct.fromJson(Map<String, dynamic> json) {
    return StoreProduct(
      id: json['id'] as String,
      name: json['name'] as String,
      url: json['url'] as String,
      sku: json['sku'] as String?,
      brand: json['brand'] as String?,
      price: json['current_price'],
      currency: json['currency'] as String,
      isAvailable: json['is_available'] as bool?,
      imageUrl: json['image_url'] as String?,
    );
  }

  final String id;
  final String name;
  final String url;
  final String? sku;
  final String? brand;
  final DecimalValue? price;
  final String currency;
  final bool? isAvailable;
  final String? imageUrl;

  String get details => [
    ?brand,
    if (sku != null) 'SKU $sku',
    switch (isAvailable) {
      true => 'В наличии',
      false => 'Нет в наличии',
      null => 'Наличие не указано',
    },
  ].join(' · ');

  String get priceLabel => price == null
      ? 'Цена не указана'
      : '${price!.toStringAsFixed(2)} $currency';
}

class ProductPage {
  const ProductPage({
    required this.items,
    required this.total,
    this.limit = 100,
    this.offset = 0,
  });

  factory ProductPage.fromJson(Map<String, dynamic> json) {
    return ProductPage(
      items: (json['items'] as List<dynamic>)
          .map((item) => StoreProduct.fromJson(item as Map<String, dynamic>))
          .toList(growable: false),
      total: (json['total'] as num).toInt(),
      limit: (json['limit'] as num?)?.toInt() ?? 100,
      offset: (json['offset'] as num?)?.toInt() ?? 0,
    );
  }

  final List<StoreProduct> items;
  final int total;
  final int limit;
  final int offset;

  bool get hasMore => offset + items.length < total;
}

/// One product found outside the store currently on screen.
class CrossStoreMatch {
  CrossStoreMatch({
    required this.source,
    required this.storeId,
    required this.storeName,
    required this.marketplace,
    required this.name,
    required this.url,
    required this.sku,
    required this.brand,
    required Object? price,
    required this.currency,
    required this.imageUrl,
    required this.matchedOn,
    required this.matchedValue,
    required this.viaCross,
  }) : price = DecimalValue.tryParse(price);

  factory CrossStoreMatch.fromJson(Map<String, dynamic> json) {
    return CrossStoreMatch(
      source: json['source'] as String,
      storeId: json['store_id'] as String?,
      storeName: json['store_name'] as String,
      marketplace: json['marketplace'] as String,
      name: json['name'] as String,
      url: json['url'] as String,
      sku: json['sku'] as String?,
      brand: json['brand'] as String?,
      price: json['price'],
      currency: json['currency'] as String,
      imageUrl: json['image_url'] as String?,
      matchedOn: json['matched_on'] as String,
      matchedValue: json['matched_value'] as String,
      viaCross: json['via_cross'] as bool? ?? false,
    );
  }

  final String source;
  final String? storeId;
  final String storeName;
  final String marketplace;
  final String name;
  final String url;
  final String? sku;
  final String? brand;
  final DecimalValue? price;
  final String currency;
  final String? imageUrl;

  /// `oem`, `sku`, or `name`: which field carried the match.
  final String matchedOn;
  final String matchedValue;
  final bool viaCross;

  /// A match inside a connected store can be opened in Marko itself.
  bool get isConnectedStore => storeId != null;

  String get priceLabel =>
      price == null ? '' : '${price!.toStringAsFixed(2)} $currency';
}

class CrossStoreSearch {
  const CrossStoreSearch({
    required this.query,
    required this.normalizedQuery,
    required this.matches,
  });

  factory CrossStoreSearch.fromJson(Map<String, dynamic> json) {
    return CrossStoreSearch(
      query: json['query'] as String,
      normalizedQuery: json['normalized_query'] as String,
      matches: (json['matches'] as List<dynamic>)
          .map((item) => CrossStoreMatch.fromJson(item as Map<String, dynamic>))
          .toList(growable: false),
    );
  }

  final String query;
  final String normalizedQuery;
  final List<CrossStoreMatch> matches;
}

class StoresState {
  const StoresState({
    this.stores = const [],
    this.isSubmitting = false,
    this.deletingStoreId,
    this.activeSync,
    this.activeJob,
    this.error,
  });

  final List<StoreSummary> stores;
  final bool isSubmitting;
  final String? deletingStoreId;
  final StoreSync? activeSync;
  final SyncRun? activeJob;
  final String? error;

  bool get hasActiveJob => activeSync != null && activeJob?.isFinished != true;
  bool get isDeleting => deletingStoreId != null;

  StoresState copyWith({
    List<StoreSummary>? stores,
    bool? isSubmitting,
    String? deletingStoreId,
    StoreSync? activeSync,
    SyncRun? activeJob,
    String? error,
    bool clearJob = false,
    bool clearSync = false,
    bool clearDeletingStore = false,
    bool clearError = false,
  }) {
    return StoresState(
      stores: stores ?? this.stores,
      isSubmitting: isSubmitting ?? this.isSubmitting,
      deletingStoreId: clearDeletingStore
          ? null
          : deletingStoreId ?? this.deletingStoreId,
      activeSync: clearSync ? null : activeSync ?? this.activeSync,
      activeJob: clearSync || clearJob ? null : activeJob ?? this.activeJob,
      error: clearError ? null : error ?? this.error,
    );
  }
}

class StoreProductsState {
  const StoreProductsState({
    required this.store,
    required this.page,
    this.query = '',
    this.isLoadingMore = false,
    this.isSearching = false,
    this.isSearchingElsewhere = false,
    this.elsewhere,
    this.error,
  });

  final StoreSummary store;
  final ProductPage page;
  final String query;
  final bool isLoadingMore;
  final bool isSearching;
  final bool isSearchingElsewhere;

  /// Populated only once the query returned nothing inside this store.
  final CrossStoreSearch? elsewhere;
  final String? error;

  bool get hasQuery => query.trim().isNotEmpty;
  bool get isEmptyResult => hasQuery && page.items.isEmpty && !isSearching;

  StoreProductsState copyWith({
    ProductPage? page,
    String? query,
    bool? isLoadingMore,
    bool? isSearching,
    bool? isSearchingElsewhere,
    CrossStoreSearch? elsewhere,
    String? error,
    bool clearElsewhere = false,
    bool clearError = false,
  }) {
    return StoreProductsState(
      store: store,
      page: page ?? this.page,
      query: query ?? this.query,
      isLoadingMore: isLoadingMore ?? this.isLoadingMore,
      isSearching: isSearching ?? this.isSearching,
      isSearchingElsewhere: isSearchingElsewhere ?? this.isSearchingElsewhere,
      elsewhere: clearElsewhere ? null : elsewhere ?? this.elsewhere,
      error: clearError ? null : error ?? this.error,
    );
  }
}
