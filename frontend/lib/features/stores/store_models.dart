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
    final local = value.toLocal().toString();
    final formatted = local.length >= 16 ? local.substring(0, 16) : local;
    return 'обновлён $formatted';
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
    'queued' => 'в очереди',
    'running' => 'выполняется',
    'completed' => 'готово',
    'failed' => 'ошибка',
    _ => status,
  };

  double? get progress {
    final total = progressTotal;
    if (total != null && total > 0) return progressCurrent / total;
    return status == 'completed' ? 1 : null;
  }
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

  String get details => [
    ?brand,
    if (sku != null) 'SKU $sku',
    isAvailable == true ? 'В наличии' : 'Нет в наличии',
  ].join(' · ');

  String get priceLabel => price == null
      ? 'Цена не указана'
      : '${price!.toStringAsFixed(2)} $currency';
}

class ProductPage {
  const ProductPage({required this.items, required this.total});

  factory ProductPage.fromJson(Map<String, dynamic> json) {
    return ProductPage(
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

class StoresState {
  const StoresState({
    this.stores = const [],
    this.isSubmitting = false,
    this.activeSync,
    this.activeJob,
    this.error,
  });

  final List<StoreSummary> stores;
  final bool isSubmitting;
  final StoreSync? activeSync;
  final SyncRun? activeJob;
  final String? error;

  bool get hasActiveJob => activeSync != null && activeJob?.isFinished != true;

  StoresState copyWith({
    List<StoreSummary>? stores,
    bool? isSubmitting,
    StoreSync? activeSync,
    SyncRun? activeJob,
    String? error,
    bool clearJob = false,
    bool clearError = false,
  }) {
    return StoresState(
      stores: stores ?? this.stores,
      isSubmitting: isSubmitting ?? this.isSubmitting,
      activeSync: activeSync ?? this.activeSync,
      activeJob: clearJob ? null : activeJob ?? this.activeJob,
      error: clearError ? null : error ?? this.error,
    );
  }
}

class StoreProductsState {
  const StoreProductsState({
    required this.store,
    required this.page,
    this.isLoadingMore = false,
    this.error,
  });

  final StoreSummary store;
  final ProductPage page;
  final bool isLoadingMore;
  final String? error;

  StoreProductsState copyWith({
    ProductPage? page,
    bool? isLoadingMore,
    String? error,
    bool clearError = false,
  }) {
    return StoreProductsState(
      store: store,
      page: page ?? this.page,
      isLoadingMore: isLoadingMore ?? this.isLoadingMore,
      error: clearError ? null : error ?? this.error,
    );
  }
}
